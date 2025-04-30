#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

import argparse
import asyncio
import functools
import os
import sys
import aiohttp

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

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

from pipecat.services.groq.llm import GroqLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.mcp_service import MCPClient

from bot_helper import DialOutHelper, UserAudioCollector

load_dotenv(override=True)

logger.remove(0)
logger.add(sys.stderr, level="DEBUG")

daily_api_key = os.getenv("DAILY_API_KEY", "")
daily_api_url = os.getenv("DAILY_API_URL", "https://api.daily.co/v1")

# Load system instructions from text files
with open("prompts/voicemail_detection_system_instruction.txt", "r") as f:
    voicemail_detection_system_instruction = f.read()

with open("prompts/human_conversation_system_instruction.txt", "r") as f:
    human_conversation_system_instruction = f.read()


global call_is_over
call_is_over = False


def set_call_terminated():
    global call_is_over
    call_is_over = True


def get_call_terminated() -> bool:
    return call_is_over


async def main(
    room_url: str,
    token: str,
    body: dict,
):
    dailout_helper = DialOutHelper(body=body)
    test_mode = dailout_helper.get_is_test_mode()
    print(f"_____bot.py * test_mode: {test_mode}")

    dialout_settings = dailout_helper.get_dialout_settings()
    print(f"_____bot.py * dialout_settings: {dialout_settings}")

    async with aiohttp.ClientSession() as session:
        transport = DailyTransport(
            room_url,
            token,
            "🇺🇸💭📞 American Dream Phone 🇺🇸💭📞",
            DailyParams(
                api_url=daily_api_url,
                api_key=daily_api_key,
                audio_in_enabled=True,
                audio_out_enabled=True,
                camera_out_enabled=False,
                vad_analyzer=SileroVADAnalyzer(),
                turn_analyzer=FalSmartTurnAnalyzer(
                    api_key=os.getenv("FAL_SMART_TURN_API_KEY"), aiohttp_session=session
                ),
            ),
        )

        # test voice
        tts = CartesiaTTSService(
            api_key=os.getenv("CARTESIA_API_KEY", ""),
            voice_id="b7d50908-b17c-442d-ad8d-810c63997ed9", # Helpful Woman
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
        voicemail_detection_llm = OpenAILLMService(api_key=os.getenv("OPENAI_API_KEY"))

        ##### playing around and trying different llms
        ##### different llms might like different prompts
        ##### some might be faster at voicemail detection...

        # human_conversation_llm = GroqLLMService(api_key=os.getenv("GROQ_API_KEY"))

        # human_conversation_llm = AnthropicLLMService(
        #     api_key=os.getenv("ANTHROPIC_API_KEY"), model="claude-3-7-sonnet-latest"
        # )

        # human_conversation_llm = GoogleLLMService(
        #     model="models/gemini-2.0-flash-001",  # Full model for better conversation
        #     api_key=os.getenv("GOOGLE_API_KEY"),
        #     system_instruction=human_conversation_system_instruction,
        #     tools=tools,
        # )

        # voicemail_detection_llm = GroqLLMService(api_key=os.getenv("GROQ_API_KEY"))

        # =================================
        # tools
        # =================================
        ## terminate call
        terminate_call_function = FunctionSchema(
            name="terminate_call",
            description="Call this function to terminate the call. If the switch_to_voicemail_response function has been called, wait until that response is over.",
            properties={},
            required=[],
        )

        async def terminate_call_back(params: FunctionCallParams):
            await params.llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)

        ## leave a message
        switch_to_voicemail_response = FunctionSchema(
            name="switch_to_voicemail_response",
            description="Call this function when you detect this is a voicemail system.",
            properties={},
            required=[],
        )

        async def switch_to_voicemail_callback(params: FunctionCallParams):
            message = """You are a constituent of Orleans Parish (New Orleans, Louisiana) leaving a voicemail message for a political representative. 
            Say EXACTLY this message and then terminate the call:
            'Hi, My name is Vanessa and I am a resident of Orleens parish. I'm calling today to voice my concerns. Thank you.'"""
            await params.result_callback(message)
            await params.llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)
            set_call_terminated()

        ## talk to a human
        switch_to_human_conversation_response = FunctionSchema(
            name="switch_to_human_conversation_response",
            description="Call this function when you detect this is a human.",
            properties={},
            required=[],
        )

        async def switch_to_human_conversation_callback(params: FunctionCallParams):
            # this will stop the voicemail_detection pipeline runner task
            await params.llm.push_frame(StopTaskFrame(), FrameDirection.UPSTREAM)

        human_conversation_tools = ToolsSchema(standard_tools=[terminate_call_function])

        voicemail_detection_tools = ToolsSchema(
            standard_tools=[
                # terminate_call_function,
                switch_to_voicemail_response,
                switch_to_human_conversation_response,
            ]
        )

        # only the human llm needs terminate the call function
        human_conversation_llm.register_function("terminate_call", terminate_call_back)
        # voicemail_detection_llm.register_function("terminate_call", terminate_call_back)

        # only vm dectection llm needs to be able to leave a message
        voicemail_detection_llm.register_function(
            "switch_to_voicemail_response", switch_to_voicemail_callback
        )

        # only vm dectection llm needs to be able to swith to human convo
        voicemail_detection_llm.register_function(
            "switch_to_human_conversation_response",
            switch_to_human_conversation_callback,
        )

        # mcp.run tools (fetch)
        try:
            mcp = MCPClient(server_params=os.getenv("ADP_MCP_RUN_SSE_URL"))
        except Exception as e:
            logger.error(f"error setting up mcp")
            logger.exception("error trace:")

        mcp_tools = await mcp.register_tools(human_conversation_llm)

        # combine local functions and mcp.run functions
        human_conversation_all_standard_tools = (
            mcp_tools.standard_tools + human_conversation_tools.standard_tools
        )
        human_conversation_all_tools = ToolsSchema(
            standard_tools=human_conversation_all_standard_tools
        )

        # human convo aggregator
        human_conversation_messages = [
            {"role": "system", "content": human_conversation_system_instruction}
        ]
        human_conversation_context = OpenAILLMContext(
            human_conversation_messages, human_conversation_all_tools
        )
        human_conversation_context_aggregator = (
            human_conversation_llm.create_context_aggregator(human_conversation_context)
        )

        # voicemail aggregator
        voicemail_detection_messages = [
            {"role": "system", "content": voicemail_detection_system_instruction}
        ]
        # only add local functions to voicemail_detection
        voicemail_detection_context = OpenAILLMContext(
            voicemail_detection_messages, voicemail_detection_tools
        )
        voicemail_detection_context_aggregator = (
            voicemail_detection_llm.create_context_aggregator(
                voicemail_detection_context
            )
        )

        # Set up audio collector for handling audio input
        voicemail_detection_audio_collector = UserAudioCollector(
            voicemail_detection_context, voicemail_detection_context_aggregator.user()
        )

        # =================================
        # voicemail_detection_pipeline
        # =================================
        voicemail_detection_pipeline = Pipeline(
            [
                transport.input(),  # Transport user input
                stt,
                # voicemail_detection_audio_collector,  # Collect audio frames
                voicemail_detection_context_aggregator.user(),  # User spoken responses
                voicemail_detection_llm,  # LLM
                tts,
                transport.output(),  # Transport bot output
                voicemail_detection_context_aggregator.assistant(),  # Assistant spoken responses and tool context
            ]
        )

        voicemail_detection_task = PipelineTask(
            voicemail_detection_pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                # enable_metrics=True,
            ),
        )
        # =================================

        # event handlers
        @transport.event_handler("on_joined")
        async def on_joined(transport, data):
            if not test_mode and dialout_settings:
                logger.debug("Dialout settings detected; starting dialout")
                await dailout_helper.start_dialout(transport, dialout_settings)

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
            await voicemail_detection_task.queue_frame(EndFrame())

        # =================================
        # runner
        # =================================
        # runner = PipelineRunner(force_gc=True)
        runner = PipelineRunner()
        # =================================

        # =================================
        # voicemail_detection_task
        # =================================
        # Run the voicemail_detection pipeline
        try:
            print("!!! starting voicemail_detection pipeline ☎️")
            await runner.run(voicemail_detection_task)
        except Exception as e:
            logger.error(f"☎️ Error in voicemail_detection pipeline: {e}")
            import traceback

            logger.error(traceback.format_exc())

        print("!!! Done with voicemail_detection pipeline ☎️")
        # =================================
        # =================================
        # =================================
        # =================================

        # did we leave a voice mail ? thenthe call is over
        terminated = get_call_terminated()
        if terminated:
            return
        # else, talk to the human

        # =================================
        # human_conversation_pipeline
        # =================================
        human_conversation_pipeline = Pipeline(
            [
                transport.input(),  # Transport user input
                stt,
                human_conversation_context_aggregator.user(),  # User spoken responses
                human_conversation_llm,  # LLM
                tts,
                transport.output(),  # Transport bot output
                human_conversation_context_aggregator.assistant(),  # Assistant spoken responses and tool context
            ]
        )

        human_conversation_task = PipelineTask(
            human_conversation_pipeline,
            params=PipelineParams(
                allow_interruptions=True,
                # enable_metrics=True,
            ),
        )
        # =================================

        # update the participant left handler to end both tasks
        @transport.event_handler("on_participant_left")
        async def on_participant_left(transport, participant, reason):
            await voicemail_detection_task.queue_frame(EndFrame())
            await human_conversation_task.queue_frame(EndFrame())

        # =================================
        # human_conversation_task
        # =================================
        # Run the human conversation pipeline

        try:
            print("!!! starting human_conversation pipeline 👾")
            await runner.run(human_conversation_task)
        except Exception as e:
            logger.error(f"👾 Error in human_conversation pipeline: {e}")
            import traceback

            logger.error(traceback.format_exc())

        print("!!! Done with human_conversation pipeline 👾")

        # else:
        #     await runner.cancel()
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
