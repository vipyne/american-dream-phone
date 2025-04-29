#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import argparse
import asyncio
import functools
import json
import os
import sys
import aiohttp

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from call_connection_manager import CallConfigManager, SessionManager
from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndFrame,
    EndTaskFrame,
    InputAudioRawFrame,
    StopTaskFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)

from pipecat.services.llm_service import FunctionCallParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext

from pipecat.audio.turn.smart_turn.fal_smart_turn import FalSmartTurnAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.google.google import GoogleLLMContext
from pipecat.services.google.llm import GoogleLLMService
from pipecat.transcriptions.language import Language
from pipecat.services.playht.tts import PlayHTTTSService
from pipecat.services.llm_service import LLMService  # Base LLM service class
from pipecat.transports.services.daily import (
    DailyParams,
    DailyTransport,
)

from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.mcp_service import MCPClient

from bot_helper import UserAudioCollector

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

daily_api_key = os.getenv("DAILY_API_KEY", "")
daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")

# Load system instructions from text files
with open("prompts/voicemail_system_instruction.txt", "r") as f:
    voicemail_system_instruction = f.read()

with open("prompts/human_conversation_system_instruction.txt", "r") as f:
    human_conversation_system_instruction = f.read()



async def main(
    room_url: str,
    token: str,
    body: dict,
):
    print(f"_____bot.py * main: {body}")
    test_mode = json.loads(body)["testInPrebuilt"]

    async with aiohttp.ClientSession() as session:

        transport = DailyTransport(
            room_url,
            token,
            "Voicemail Detection Bot",
            DailyParams(
                api_url=daily_api_url,
                api_key=daily_api_key,
                audio_in_enabled=True,
                audio_out_enabled=True,
                camera_out_enabled=False,
                vad_analyzer=SileroVADAnalyzer(),
                turn_analyzer=FalSmartTurnAnalyzer(
                    api_key=os.getenv("FAL_SMART_TURN_API_KEY"),
                    aiohttp_session=session
                ),
            ),
        )

        tts = CartesiaTTSService(
            api_key=os.getenv("CARTESIA_API_KEY", ""),
            voice_id="b7d50908-b17c-442d-ad8d-810c63997ed9",  # Use Helpful Woman voice by default
        )

        # ## vanessa's voice
        # tts = PlayHTTTSService(
        #     user_id=os.getenv("PLAYHT_USER_ID"),
        #     api_key=os.getenv("PLAYHT_API_KEY"),
        #     voice_url="s3://voice-cloning-zero-shot/5250872f-068a-4c17-827d-783f51319eec/vanessa-dream-02/manifest.json",
        #     params=PlayHTTTSService.InputParams(language=Language.EN),
        # )    

        stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

        human_conversation_llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))
        
        # human_conversation_llm = AnthropicLLMService(
        #     api_key=os.getenv("ANTHROPIC_API_KEY"), model="claude-3-7-sonnet-latest"
        # )

        # human_conversation_llm = GoogleLLMService(
        #     model="models/gemini-2.0-flash-001",  # Full model for better conversation
        #     api_key=os.getenv("GOOGLE_API_KEY"),
        #     system_instruction=human_conversation_system_instruction,
        #     tools=tools,
        # )



    # weather_function = FunctionSchema(
    #     name="get_weather",
    #     description="Get the current weather",
    #     properties={
    #         "location": {
    #             "type": "string",
    #             "description": "The city and state, e.g. San Francisco, CA",
    #         },
    #     },
    #     required=["location"],
    # )
    # tools = ToolsSchema(standard_tools=[weather_function])
        

        # tools

        ## terminate call
        terminate_call_function = FunctionSchema(
            name="terminate_call",
            description="Call this function to terminate the call.",
            properties={},
            required=[],
        )
        async def terminate_call_back(params: FunctionCallParams):
            await params.llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
        

        tools = ToolsSchema(standard_tools=[terminate_call_function])

        human_conversation_llm.register_function("terminate_call", terminate_call_back)

        # MCP
        try:
            mcp = MCPClient(server_params=os.getenv("ADP_MCP_RUN_SSE_URL"))
        except Exception as e:
            logger.error(f"error setting up mcp")
            logger.exception("error trace:")

        mcp_tools = await mcp.register_tools(human_conversation_llm)

        # all_standard_tools = mcp_tools.standard_tools + tools
        all_standard_tools = mcp_tools.standard_tools + tools.standard_tools
        all_tools = ToolsSchema(standard_tools=all_standard_tools)

        messages = [{"role": "system", "content": human_conversation_system_instruction}]
        human_conversation_context = OpenAILLMContext(messages, all_tools)

        human_conversation_context_aggregator = human_conversation_llm.create_context_aggregator(
            human_conversation_context
        )

        # =================================
        human_conversation_pipeline = Pipeline(
            [
                transport.input(),  # Transport user input
                stt,
                human_conversation_context_aggregator.user(),  # User spoken responses
                human_conversation_llm,  # LLM
                tts,  # TTS
                transport.output(),  # Transport bot output
                human_conversation_context_aggregator.assistant(),  # Assistant spoken responses and tool context
            ]
        )

        human_conversation_task = PipelineTask(
            human_conversation_pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                enable_metrics=True,
            ),
        )
        # =================================

        # event handlers
        @transport.event_handler("on_joined")
        async def on_joined(transport, data):
            if not test_mode and dialout_settings:
                logger.debug("Dialout settings detected; starting dialout")
                await call_config_manager.start_dialout(transport, dialout_settings)

        @transport.event_handler("on_dialout_connected")
        async def on_dialout_connected(transport, data):
            logger.debug(f"Dial-out connected: {data}")

        @transport.event_handler("on_dialout_answered")
        async def on_dialout_answered(transport, data):
            logger.debug(f"Dial-out answered: {data}")
            await transport.capture_participant_transcription(data["sessionId"])

        @transport.event_handler("on_first_participant_joined")
        async def on_first_participant_joined(transport, participant):
            logger.debug(f"First participant joined: {participant['id']}")
            if test_mode:
                await transport.capture_participant_transcription(participant["id"])

        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            await human_conversation_task.queue_frame(EndFrame())
            # await voicemail_detection_pipeline_task.queue_frame(EndFrame())


        # =================================
        runner = PipelineRunner(handle_sigint=False)
        # runner = PipelineRunner()

        # Run the human conversation pipeline
        try:
            await runner.run(human_conversation_task)
        except Exception as e:
            logger.error(f"Error in human_conversation pipeline: {e}")
            import traceback

            logger.error(traceback.format_exc())

        print("!!! Done with human_conversation pipeline")

        await runner.run(human_conversation_task)
        # =================================


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipecat Voicemail Detection Bot")
    parser.add_argument("-u", "--url", type=str, help="Room URL")
    parser.add_argument("-t", "--token", type=str, help="Room Token")
    parser.add_argument("-b", "--body", type=str, help="JSON configuration string")

    args = parser.parse_args()

    logger.info(f"Room URL: {args.url}")
    # logger.info(f"Token: {args.token}")
    logger.info(f"Body provided: {bool(args.body)}")

    asyncio.run(main(args.url, args.token, args.body))







