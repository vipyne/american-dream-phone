"""American Dream Phone API server.

Runs the FastAPI server with all routes:
- POST /start — create Daily room, launch bot
- POST /upload-voice — save voice recording for cloning
- POST /clone-voice — clone voice via Cartesia API
- POST /preview — LLM preview + moderation
- GET /representatives — look up reps by address (placeholder)

Usage::

    uv run python server.py
    # or with custom host/port:
    uv run python server.py --host 0.0.0.0 --port 8000
"""

import argparse
import asyncio
import os
import time
import uuid
from collections import defaultdict
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
# Demo mode config
# ---------------------------------------------------------------------------
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
DEV_SECRET = os.getenv("DEV_SECRET", "")  # Secret to unlock dev mode (BYOPN)
MAX_CALLS_PER_DAY = 2
MAX_CALL_DURATION_SECS = 5 * 60  # 5 minutes
VOICE_CLONING_ENABLED = not DEMO_MODE

# In-memory call counter: { "YYYY-MM-DD": count }
# Resets on server restart. Good enough without a DB.
_daily_call_counts: dict[str, int] = defaultdict(int)

# ---------------------------------------------------------------------------
# Representatives data (hardcoded for now)
# ---------------------------------------------------------------------------
REPRESENTATIVES = [
    {"name": "Sen. Bill Cassidy", "phone": "+12022245824", "level": "Federal", "state": "LA"},
    {"name": "Sen. John Kennedy", "phone": "+12022244623", "level": "Federal", "state": "LA"},
    {"name": "Rep. Troy Carter (LA-02)", "phone": "+12022258490", "level": "Federal", "state": "LA"},
]

WHITELIST_PHONES = {rep["phone"] for rep in REPRESENTATIVES}


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _calls_remaining() -> int:
    return max(0, MAX_CALLS_PER_DAY - _daily_call_counts[_today()])


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
# GET /config — expose demo mode settings to the frontend
# ---------------------------------------------------------------------------
@app.get("/config")
async def get_config():
    return {
        "demo_mode": DEMO_MODE,
        "voice_cloning_enabled": VOICE_CLONING_ENABLED,
        "max_calls_per_day": MAX_CALLS_PER_DAY,
        "calls_remaining": _calls_remaining(),
        "max_call_duration_secs": MAX_CALL_DURATION_SECS,
    }


# ---------------------------------------------------------------------------
# POST /start — create Daily room and launch bot
# ---------------------------------------------------------------------------
@app.post("/start")
async def start_agent(request: Request):
    """Create a Daily room and start the bot.

    In demo mode: requires preview_passed, enforces whitelist + rate limit.
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

    # --- Demo mode guardrails ---
    if DEMO_MODE:
        # Must have passed preview (moderation)
        if not body.get("preview_passed"):
            return JSONResponse(
                {"error": "Please preview your message before calling."},
                status_code=403,
            )

        # Rate limit
        if _calls_remaining() <= 0:
            return JSONResponse(
                {"error": f"Daily call limit reached ({MAX_CALLS_PER_DAY} calls/day). Try again tomorrow."},
                status_code=429,
            )

        # Phone whitelist (unless dev secret is provided)
        dev_secret = body.get("dev_secret", "")
        is_dev = DEV_SECRET and dev_secret == DEV_SECRET
        dialout_settings = body.get("dialout_settings", [])
        if dialout_settings and not is_dev:
            phone = dialout_settings[0].get("phoneNumber", "")
            if phone not in WHITELIST_PHONES:
                return JSONResponse(
                    {"error": "In demo mode, calls are limited to listed representatives."},
                    status_code=403,
                )

    # --- Proceed with call ---
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

            # Inject max call duration into body so bot.py can use it
            body["max_call_duration_secs"] = MAX_CALL_DURATION_SECS

            runner_args = DailyRunnerArguments(room_url=room_url, token=token, body=body)
            result = {
                "dailyRoom": room_url,
                "dailyToken": token,
                "sessionId": str(uuid.uuid4()),
            }
    else:
        runner_args = DailyRunnerArguments(
            room_url=body.get("room_url", ""),
            token=body.get("token", ""),
            body=body,
        )
        result = {"sessionId": str(uuid.uuid4())}

    # Increment call counter
    _daily_call_counts[_today()] += 1

    # Import and launch the bot in the background
    import bot

    asyncio.create_task(bot.bot(runner_args))

    result["calls_remaining"] = _calls_remaining()
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
    Disabled in demo mode.
    """
    if not VOICE_CLONING_ENABLED:
        return JSONResponse(
            {"error": "Voice cloning is temporarily disabled in demo mode."},
            status_code=403,
        )

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
# POST /preview — preview what the bot would say + moderation
# ---------------------------------------------------------------------------
MODERATION_PROMPT = """You are a content moderator for a civic engagement tool that helps constituents call their political representatives. Evaluate the user's message below.

APPROVE the message if it is:
- A legitimate constituent concern (healthcare, taxes, legislation, etc.)
- A call script from an advocacy organization
- Polite, assertive, or passionate — even if angry — as long as it's about a real issue

REJECT the message if it is:
- A prank, joke, or clearly not a real constituent message
- Threats of violence or harassment
- Spam, gibberish, or nonsensical content
- Hate speech or slurs

Respond with ONLY a JSON object (no markdown):
{"approved": true} or {"approved": false, "reason": "brief explanation"}"""


@app.post("/preview")
async def preview_call(request: Request):
    """Generate a preview of what the bot would say on the call.

    Also runs moderation on the user's message. Returns approved: true/false.
    """
    from bot import build_substitution_data, human_conversation_system_instruction, voicemail_message_template

    data = await request.json()

    sub_data = build_substitution_data(data)
    voicemail_message = voicemail_message_template.format(**sub_data)
    issue_text = data.get("issue_text", "")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"}, status_code=500)

    # --- Run moderation + preview in parallel ---
    moderation_result = {"approved": True}
    human_preview = ""

    async with aiohttp.ClientSession() as session:
        # Build both requests
        moderation_body = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 256,
            "system": MODERATION_PROMPT,
            "messages": [
                {"role": "user", "content": issue_text or "(no message provided)"},
            ],
        }

        system_prompt = human_conversation_system_instruction
        if issue_text:
            system_prompt += (
                f"\n\nThe constituent's message about their issue:\n{issue_text}\n\n"
                "Incorporate the above concerns into your conversation. "
                "Stay faithful to the constituent's words — do not add claims or facts they did not provide."
            )

        preview_body = {
            "model": "claude-sonnet-4-6",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": "Hello, Senator's office, how can I help you?"},
            ],
        }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Fire both requests concurrently
        async def call_anthropic(body):
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                json=body,
                headers=headers,
            ) as resp:
                return resp.status, await resp.json()

        mod_task = asyncio.create_task(call_anthropic(moderation_body))
        preview_task = asyncio.create_task(call_anthropic(preview_body))

        mod_status, mod_data = await mod_task
        preview_status, preview_data = await preview_task

    # Parse moderation
    if mod_status == 200:
        mod_text = mod_data.get("content", [{}])[0].get("text", "")
        try:
            import json
            moderation_result = json.loads(mod_text)
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"Failed to parse moderation response: {mod_text}")
            moderation_result = {"approved": True}  # fail open
    else:
        logger.error(f"Moderation call failed: {mod_status} {mod_data}")

    # Parse preview
    if preview_status == 200:
        human_preview = preview_data.get("content", [{}])[0].get("text", "")
    else:
        logger.error(f"Anthropic preview failed: {preview_status} {preview_data}")
        human_preview = "(Preview unavailable — LLM error)"

    return {
        "voicemail": voicemail_message,
        "human_conversation": human_preview,
        "moderation": moderation_result,
        "calls_remaining": _calls_remaining(),
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
    if DEMO_MODE:
        print(f"  → Demo mode ON ({MAX_CALLS_PER_DAY} calls/day, {MAX_CALL_DURATION_SECS // 60}min limit, whitelist only)")
    else:
        print(f"  → Demo mode OFF (unrestricted)")
    print()

    uvicorn.run(app, host=args.host, port=args.port)
