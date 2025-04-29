import argparse
import json
import os
import shlex
import subprocess
from contextlib import asynccontextmanager
from typing import Any, Callable, Dict, List, Optional

import inspect

import aiohttp

# Maximum session time
MAX_SESSION_TIME = 5 * 60  # 5 minutes

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from pipecat.transports.services.helpers.daily_rest import (
    DailyRESTHelper,
    DailyRoomParams,
    DailyRoomProperties,
)

load_dotenv(override=True)

daily_api_key = os.getenv("DAILY_API_KEY", "")
daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")
room_url = os.getenv("DAILY_SAMPLE_ROOM_URL", None)

BOT_FILENAME="voicemail_detection"
BOT_FILENAME="bot"

daily_helpers = {}

async def start_bot(room_details: Dict[str, str], body: Dict[str, Any], bot_filename: str) -> bool:
    """Start a bot process with the given configuration.
    Args:
        room_details: Room URL and token
        body: Bot configuration
    Returns:
        Boolean indicating success
    """
    room_url = room_details["room_url"]
    token = room_details["token"]

    body_json = json.dumps(body).replace('"', '\\"')
    print(f"++++ Body JSON: {body_json}")

    bot_proc = f'python3 -m {bot_filename} -u {room_url} -t {token} -b "{body_json}"'
    print(f"Starting bot. Room: {room_url}")

    try:
        command_parts = shlex.split(bot_proc)
        subprocess.Popen(command_parts, bufsize=1, cwd=os.path.dirname(os.path.abspath(__file__)))
        return True
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    aiohttp_session = aiohttp.ClientSession()
    daily_helpers["rest"] = DailyRESTHelper(
        daily_api_key=daily_api_key,
        daily_api_url=daily_api_url,
        aiohttp_session=aiohttp_session,
    )
    blah = daily_helpers["rest"]
    # print(f"_____bot_runner.py * daily_helpers[rest]: {blah}")
    # print(f"_____bot_runner.py * dir(blah): {dir(blah)}")
    # print(f"_____bot_runner.py * inspect.signature(blah.create_room): {inspect.signature(blah.create_room)}")

    yield
    await aiohttp_session.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/start")
async def handle_start_request(request: Request) -> JSONResponse:
    """Unified endpoint to handle bot configuration for different scenarios."""

    bot_filename = BOT_FILENAME
    room_url = os.getenv("DAILY_SAMPLE_ROOM_URL", None)
    if not room_url:
        params = DailyRoomParams(properties={"start_video_off":True})
        room = await daily_helpers["rest"].create_room(params)
        # print(f"_<>____bot_runner.py * room: {room}")
        room_url = room.url

    try:
        data = await request.json()
        
        # {'voicemail_detection': {'testInPrebuilt': True}}
        body = data['config']
        token = await daily_helpers["rest"].get_token(room_url, MAX_SESSION_TIME)
        room_details = {"room_url": room_url, "token": token}
        
        await start_bot(room_details, body, bot_filename)

        response = {"status": "Bot started", "bot_type": bot_filename}
        
        # pstn (phone)
        if "dialout_settings" in body and len(body["dialout_settings"]) > 0:
            number = body["dialout_settings"][0]
            response["dialing_to"] = f"phone:{number['phoneNumber']}"

        # test (webrtc)
        # is_test_mode = body[bot_filename]["testInPrebuilt"]
        is_test_mode = body["testInPrebuilt"]
        if is_test_mode:
            response["room_url"] = room_details["room_url"]

        print(f"_____bot_runner.py * response: {response}")
        # {'status': 'Bot started', 'bot_type': 'voicemail_detection', 'dialing_to': 'phone:+16665554444'}
        return JSONResponse(response)

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Request processing error: {str(e)}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Pipecat Bot Runner")
    parser.add_argument(
        "--host", type=str, default=os.getenv("HOST", "0.0.0.0"), help="Host address"
    )
    parser.add_argument("--port", type=int, default=os.getenv("PORT", 7860), help="Port number")
    parser.add_argument("--reload", action="store_true", default=True, help="Reload code on change")

    config = parser.parse_args()
    print(f"_____bot_runner.py * Pipecat Bot Runner config: {config}")

    try:
        import uvicorn

        uvicorn.run("bot_runner:app", host=config.host, port=config.port, reload=config.reload)

    except KeyboardInterrupt:
        print("Pipecat runner shutting down...")
