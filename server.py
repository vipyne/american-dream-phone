"""American Dream Phone API server.

Runs the FastAPI server with all routes:
- POST /start — create Daily room, launch bot
- POST /upload-voice — save voice recording for cloning
- POST /clone-voice — clone voice via Cartesia API
- GET /representatives — look up reps by address (placeholder)

Usage::

    uv run python server.py
    # or with custom host/port:
    uv run python server.py --host 0.0.0.0 --port 8000
"""

import argparse
import asyncio
import os
import uuid
from pathlib import Path

import aiohttp
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

load_dotenv(override=True)

RECORDINGS_DIR = Path(__file__).parent / "temp_local_recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Representatives data (hardcoded for now)
# ---------------------------------------------------------------------------
REPRESENTATIVES = [
    {"name": "Sen. Bill Cassidy", "phone": "+12022245824", "level": "Federal", "state": "LA"},
    {"name": "Sen. John Kennedy", "phone": "+12022244623", "level": "Federal", "state": "LA"},
    {"name": "Rep. Troy Carter (LA-02)", "phone": "+12022258490", "level": "Federal", "state": "LA"},
]

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="American Dream Phone")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# POST /start — create Daily room and launch bot
# ---------------------------------------------------------------------------
@app.post("/start")
async def start_agent(request: Request):
    """Create a Daily room and start the bot.

    Expects::

        {
            "createDailyRoom": true,
            "dailyRoomProperties": { "enable_dialout": true },
            "body": {
                "dialout_settings": [{"phoneNumber": "+1..."}],
                "constituent_name": "...",
                "issue_text": "...",
                ...
            }
        }
    """
    from pipecat.runner.daily import configure
    from pipecat.runner.types import DailyRunnerArguments
    from pipecat.transports.daily.utils import DailyRoomProperties

    try:
        request_data = await request.json()
    except Exception:
        request_data = {}

    body = request_data.get("body", {})
    create_room = request_data.get("createDailyRoom", False)
    room_props_dict = request_data.get("dailyRoomProperties", None)

    result = None

    if create_room:
        room_properties = None
        if room_props_dict:
            try:
                room_properties = DailyRoomProperties(**room_props_dict)
            except Exception as e:
                logger.error(f"Failed to parse dailyRoomProperties: {e}")

        async with aiohttp.ClientSession() as session:
            room_url, token = await configure(session, room_properties=room_properties)
            runner_args = DailyRunnerArguments(room_url=room_url, token=token, body=body)
            result = {
                "dailyRoom": room_url,
                "dailyToken": token,
                "sessionId": str(uuid.uuid4()),
            }
    else:
        from pipecat.runner.types import RunnerArguments

        runner_args = DailyRunnerArguments(
            room_url=body.get("room_url", ""),
            token=body.get("token", ""),
            body=body,
        )
        result = {"sessionId": str(uuid.uuid4())}

    # Import and launch the bot in the background
    import bot

    asyncio.create_task(bot.bot(runner_args))

    return result


# ---------------------------------------------------------------------------
# POST /upload-voice — save voice recording
# ---------------------------------------------------------------------------
@app.post("/upload-voice")
async def upload_voice(request: Request):
    """Save a voice recording to temp_local_recordings/.

    Accepts raw audio bytes (audio/webm) in the request body.
    Returns the filename and path.
    """
    audio_bytes = await request.body()
    if not audio_bytes:
        return JSONResponse({"error": "No audio data received"}, status_code=400)

    filename = f"voice-clone-{uuid.uuid4().hex[:8]}-{int(asyncio.get_event_loop().time())}.webm"
    filepath = RECORDINGS_DIR / filename
    filepath.write_bytes(audio_bytes)

    logger.info(f"Saved voice recording: {filepath} ({len(audio_bytes)} bytes)")
    return {"filename": filename, "path": str(filepath)}


# ---------------------------------------------------------------------------
# POST /clone-voice — clone voice via Cartesia API
# ---------------------------------------------------------------------------
@app.post("/clone-voice")
async def clone_voice(request: Request):
    """Clone a voice using Cartesia's API.

    Expects::

        { "filename": "voice-clone-xxxx.webm" }

    Returns the Cartesia voice ID on success.
    """
    data = await request.json()
    filename = data.get("filename")
    if not filename:
        return JSONResponse({"error": "filename is required"}, status_code=400)

    filepath = RECORDINGS_DIR / filename
    if not filepath.exists():
        return JSONResponse({"error": f"File not found: {filename}"}, status_code=404)

    api_key = os.getenv("CARTESIA_API_KEY")
    if not api_key:
        return JSONResponse({"error": "CARTESIA_API_KEY not configured"}, status_code=500)

    # Cartesia clone API: POST /voices/clone/clip
    async with aiohttp.ClientSession() as session:
        form = aiohttp.FormData()
        form.add_field(
            "clip",
            filepath.read_bytes(),
            filename=filename,
            content_type="audio/webm",
        )

        async with session.post(
            "https://api.cartesia.ai/voices/clone/clip",
            data=form,
            headers={
                "X-API-Key": api_key,
                "Cartesia-Version": "2024-06-10",
            },
        ) as resp:
            resp_data = await resp.json()

            if resp.status != 200:
                logger.error(f"Cartesia clone failed: {resp.status} {resp_data}")
                return JSONResponse(
                    {"error": "Voice cloning failed", "detail": resp_data},
                    status_code=resp.status,
                )

            voice_id = resp_data.get("id")
            logger.info(f"Voice cloned successfully: {voice_id}")
            return {"voice_id": voice_id, "detail": resp_data}


# ---------------------------------------------------------------------------
# POST /preview — preview what the bot would say
# ---------------------------------------------------------------------------
@app.post("/preview")
async def preview_call(request: Request):
    """Generate a preview of what the bot would say on the call.

    Uses the same prompts and LLM as the actual bot to produce realistic output.

    Expects::

        {
            "constituent_name": "...",
            "constituent_address": "...",
            "constituent_phone_number": "...",
            "rep_name": "...",
            "issue_text": "..."
        }
    """
    from bot import build_substitution_data, human_conversation_system_instruction, voicemail_message_template

    data = await request.json()

    sub_data = build_substitution_data(data)
    voicemail_message = voicemail_message_template.format(**sub_data)
    issue_text = data.get("issue_text", "")

    # Build the system prompt for the human conversation preview
    # If the user provided issue_text, incorporate it into the prompt
    system_prompt = human_conversation_system_instruction
    if issue_text:
        system_prompt += (
            f"\n\nThe constituent's message about their issue:\n{issue_text}\n\n"
            "Incorporate the above concerns into your conversation. "
            "Stay faithful to the constituent's words — do not add claims or facts they did not provide."
        )

    # Call the LLM for the human conversation preview
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"}, status_code=500)

    human_preview = ""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.anthropic.com/v1/messages",
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1024,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": "Hello, Senator's office, how can I help you?"},
                    ],
            },
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        ) as resp:
            resp_data = await resp.json()
            if resp.status == 200:
                human_preview = resp_data.get("content", [{}])[0].get("text", "")
            else:
                logger.error(f"Anthropic preview failed: {resp.status} {resp_data}")
                human_preview = "(Preview unavailable — LLM error)"

    return {
        "voicemail": voicemail_message,
        "human_conversation": human_preview,
    }


# ---------------------------------------------------------------------------
# GET /representatives — look up reps by address (placeholder)
# ---------------------------------------------------------------------------
@app.get("/representatives")
async def get_representatives(address: str = ""):
    """Look up representatives by address.

    Currently returns hardcoded New Orleans + Federal LA reps.
    Future: integrate BallotReady or 5calls API.
    """
    # TODO: Use address to look up actual representatives
    # For now, return the hardcoded list regardless of address
    return {"address": address, "representatives": REPRESENTATIVES}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="American Dream Phone server")
    parser.add_argument("--host", default="localhost", help="Server host (default: localhost)")
    parser.add_argument("--port", type=int, default=7860, help="Server port (default: 7860)")
    args = parser.parse_args()

    print()
    print(f"  American Dream Phone server")
    print(f"  → http://{args.host}:{args.port}")
    print()

    uvicorn.run(app, host=args.host, port=args.port)
