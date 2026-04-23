#
# Copyright (c) 2024–2025, Daily
#
# SPDX-License-Identifier: BSD 2-Clause License
#

"""American Dream Phone Bot.

AI-powered constituent phone call bot using IVR navigation.

Run locally with Daily transport::

    python bot.py -t daily

Then start a test session::

    curl -X POST http://localhost:7860/start \\
      -H "Content-Type: application/json" \\
      -d '{"createDailyRoom": true, "body": {"testInPrebuilt": true}}'

Or start a dialout session::

    curl -X POST http://localhost:7860/start \\
      -H "Content-Type: application/json" \\
      -d '{"createDailyRoom": true, "dailyRoomProperties": {"enable_dialout": true}, "body": {"dialout_settings": [{"phoneNumber": "+1XXXXXXXXXX"}]}}'
"""

import asyncio
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.extensions.ivr.ivr_navigator import IVRNavigator, IVRStatus
from pipecat.frames.frames import (
    EndFrame,
    EndTaskFrame,
    LLMMessagesUpdateFrame,
    TextFrame,
    VADParamsUpdateFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.runner.types import DailyRunnerArguments, RunnerArguments
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.base_transport import BaseTransport
from pipecat.transports.daily.transport import DailyParams, DailyTransport

load_dotenv(override=True)


DEFAULT_SUBSTITUTION_DATA = {
    "constituent_name": "Vanessa",
    "rep": "Senator Bill Cassidy",
    "constituent_state": "Louisiana",
    "constituent_phone_number": os.getenv("CONSTITUENT_PHONE_NUMBER"),
    "issue_text": "",
}

# Load prompt templates
with open("prompts/vm_001_hr1.txt", "r") as f:
    voicemail_message_template = f.read()

with open("prompts/human_conversation_system_instruction.txt", "r") as f:
    human_conversation_system_instruction = f.read()


def build_substitution_data(body: dict) -> dict:
    """Build prompt substitution data from request body, falling back to defaults."""
    return {
        "constituent_name": body.get("constituent_name", DEFAULT_SUBSTITUTION_DATA["constituent_name"]),
        "rep": body.get("rep_name", DEFAULT_SUBSTITUTION_DATA["rep"]),
        "constituent_state": body.get("constituent_state", DEFAULT_SUBSTITUTION_DATA["constituent_state"]),
        "constituent_phone_number": body.get("constituent_phone_number", DEFAULT_SUBSTITUTION_DATA["constituent_phone_number"]),
        "issue_text": body.get("issue_text", DEFAULT_SUBSTITUTION_DATA["issue_text"]),
    }

VOICEMAIL_INDICATORS = [
    "leave a message",
    "after the beep",
    "after the tone",
    "no one is available",
    "record your message",
    "you have reached voicemail",
    "is unavailable",
    "is not available",
    "the person you are trying to reach",
    "the number you have dialed",
    "voice messaging system",
    "voicemail",
    "voice mail",
    "mailbox is full",
    "not in the office",
    "out of the office",
    "currently closed",
    "office is closed",
    "office hours",
    "call back",
    "call us back",
    "please try again",
    "god bless the united states",
    "beep",
]


def check_for_voicemail(conversation_history: list) -> bool:
    """Check conversation history for voicemail indicators."""
    for message in conversation_history:
        content = message.get("content", "").lower()
        for indicator in VOICEMAIL_INDICATORS:
            if indicator in content:
                logger.info(f"Voicemail detected: found '{indicator}' in conversation")
                return True
    return False


def get_dialout_settings(body: dict) -> Optional[List[Dict[str, Any]]]:
    """Extract dialout settings from the body."""
    settings = body.get("dialout_settings")
    if isinstance(settings, dict):
        return [settings]
    if isinstance(settings, list):
        return settings
    return None


async def start_dialout(transport, dialout_settings: List[Dict[str, Any]]):
    """Start dialout using the provided settings."""
    for setting in dialout_settings:
        if "phoneNumber" in setting:
            logger.info(f"Dialing number: {setting['phoneNumber']}")
            dialout_params = {"phoneNumber": setting["phoneNumber"]}
            if "callerId" in setting:
                dialout_params["callerId"] = setting["callerId"]
            await transport.start_dialout(dialout_params)
        elif "sipUri" in setting:
            logger.info(f"Dialing sipUri: {setting['sipUri']}")
            await transport.start_dialout({"sipUri": setting["sipUri"]})


async def run_bot(
    transport: BaseTransport,
    handle_sigint: bool,
    body: dict,
) -> None:
    """Run the bot with a single pipeline.

    Uses IVRNavigator for initial classification and IVR navigation.
    When a human is detected, swaps the LLM prompt to conversation mode inline.
    When voicemail is detected, leaves a message and ends.
    """

    dialout_settings = get_dialout_settings(body)
    test_mode = "testInPrebuilt" in body

    # Build prompt data from request body (frontend passes these) or use defaults
    sub_data = build_substitution_data(body)
    voicemail_message = voicemail_message_template.format(**sub_data)
    issue_text = body.get("issue_text", "")

    logger.info(f"test_mode: {test_mode}, dialout_settings: {dialout_settings}")
    logger.info(f"Constituent: {sub_data['constituent_name']}, Rep: {sub_data['rep']}")

    # =================================
    # Services
    # =================================
    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY", ""),
        settings=CartesiaTTSService.Settings(
            voice="b7d50908-b17c-442d-ad8d-810c63997ed9",  # Helpful Woman
        ),
    )

    llm = AnthropicLLMService(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        settings=AnthropicLLMService.Settings(
            model="claude-sonnet-4-6",
        ),
    )

    # =================================
    # Tools (available throughout the call)
    # =================================
    terminate_call_function = FunctionSchema(
        name="terminate_call",
        description="Call this function to terminate the call.",
        properties={},
        required=[],
    )

    async def terminate_call_back(params: FunctionCallParams):
        await params.llm.queue_frame(EndTaskFrame(), FrameDirection.UPSTREAM)

    llm.register_function("terminate_call", terminate_call_back)

    tools = ToolsSchema(standard_tools=[terminate_call_function])

    # =================================
    # IVR Navigator (uses the same LLM)
    # =================================
    ivr_navigator = IVRNavigator(
        llm=llm,
        ivr_prompt="""You are calling a political representative's office. Your goal is to speak with someone about a constituent's concerns. If asked to press a button or make a selection, choose the option to speak with a representative or leave a message.

VOICEMAIL DETECTION: If you hear any voicemail indicators such as "leave a message", "after the beep", "after the tone", "no one is available", "voicemail", "is unavailable", "office is closed", "office hours", "call back later", or similar — immediately respond with <mode>conversation</mode> to switch to message-leaving mode. Do NOT try to navigate voicemail as an IVR menu.""",
    )

    # Context + aggregators
    context = LLMContext(tools=tools)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
        ),
    )

    # =================================
    # Single Pipeline
    # =================================
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            ivr_navigator,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(allow_interruptions=True),
    )

    # =================================
    # IVR Event: conversation detected
    # =================================
    @ivr_navigator.event_handler("on_conversation_detected")
    async def on_conversation_detected(processor, conversation_history):
        logger.info(f"Conversation detected. History: {conversation_history}")

        is_voicemail = check_for_voicemail(conversation_history)

        if is_voicemail:
            logger.info("Voicemail detected — leaving message directly via TTS")
            # Use processor.push_frame to send text downstream directly to TTS,
            # bypassing the LLM (task.queue_frame would route through the LLM
            # which would "describe" the message instead of speaking it).
            await processor.push_frame(TextFrame(text=voicemail_message))
            await processor.push_frame(EndFrame())
        else:
            logger.info("Human detected — switching to conversation mode")
            system_prompt = human_conversation_system_instruction
            message_mode = body.get("message_mode", "freestyle")
            if message_mode == "template" and issue_text:
                system_prompt += (
                    f"\n\nThe constituent has provided a call script. Use it as closely as possible:\n{issue_text}\n\n"
                    "Deliver this script faithfully. Do not add, remove, or rephrase the constituent's words."
                )
            elif issue_text:
                system_prompt += (
                    f"\n\nThe constituent described their concern:\n{issue_text}\n\n"
                    "Craft an articulate, concise message that captures their intent. "
                    "Stay faithful to their concerns — do not add claims or facts they did not provide. "
                    "Be polite but assertive."
                )
            messages = [
                {"role": "system", "content": system_prompt}
            ]
            if conversation_history:
                messages.extend(conversation_history)
            await task.queue_frame(
                LLMMessagesUpdateFrame(messages=messages, run_llm=True)
            )
            # Reduce VAD stop_secs for natural conversation flow
            await task.queue_frame(
                VADParamsUpdateFrame(params=VADParams(stop_secs=0.8))
            )

    @ivr_navigator.event_handler("on_ivr_status_changed")
    async def on_ivr_status_changed(processor, status):
        logger.info(f"IVR status changed: {status}")
        if status == IVRStatus.COMPLETED:
            logger.info("IVR navigation completed successfully")
        elif status == IVRStatus.STUCK:
            logger.warning("IVR navigation stuck — ending call")
            await task.queue_frame(EndFrame())

    # =================================
    # Transport events + dialout retry
    # =================================
    max_retries = 5
    retry_count = 0
    dialout_successful = False

    async def attempt_dialout(transport, dialout_settings: List[Dict[str, Any]]):
        nonlocal retry_count, dialout_successful
        if retry_count < max_retries and not dialout_successful:
            retry_count += 1
            logger.info(f"Attempting dialout (attempt {retry_count}/{max_retries})")
            await start_dialout(transport, dialout_settings)
        else:
            logger.error(f"Maximum retry attempts ({max_retries}) reached.")
            await task.cancel()

    @transport.event_handler("on_joined")
    async def on_joined(transport, data):
        if dialout_settings:
            logger.debug("Dialout settings detected; starting dialout")
            await attempt_dialout(transport, dialout_settings)

    @transport.event_handler("on_dialout_connected")
    async def on_dialout_connected(transport, data):
        logger.debug(f"Dial-out connected: {data}")

    @transport.event_handler("on_dialout_answered")
    async def on_dialout_answered(transport, data):
        nonlocal dialout_successful
        logger.debug(f"Dial-out answered: {data}")
        dialout_successful = True
        await transport.capture_participant_transcription(data["sessionId"])

    @transport.event_handler("on_dialout_error")
    async def on_dialout_error(transport, data: Any):
        logger.error(f"Dial-out error (attempt {retry_count}/{max_retries}): {data}")
        if retry_count < max_retries and dialout_settings:
            logger.info("Retrying dialout")
            await attempt_dialout(transport, dialout_settings)
        else:
            logger.error(f"All {max_retries} dialout attempts failed. Stopping bot.")
            await task.cancel()

    @transport.event_handler("on_first_participant_joined")
    async def on_first_participant_joined(transport, participant):
        logger.debug(f"First participant joined: {participant['id']}")
        if test_mode:
            await transport.capture_participant_transcription(participant["id"])

    @transport.event_handler("on_participant_left")
    async def on_participant_left(transport, participant, reason):
        logger.debug(f"Participant left: {participant}, reason: {reason}")
        await task.cancel()

    # =================================
    # Auto-hangup timer (demo mode)
    # =================================
    max_duration = body.get("max_call_duration_secs", 0)

    async def _auto_hangup():
        await asyncio.sleep(max_duration)
        logger.warning(f"Auto-hangup: call exceeded {max_duration}s limit")
        await task.queue_frame(EndFrame())

    hangup_timer = None
    if max_duration > 0:
        hangup_timer = asyncio.create_task(_auto_hangup())

    # =================================
    # Run
    # =================================
    runner = PipelineRunner(handle_sigint=handle_sigint)
    await runner.run(task)

    if hangup_timer and not hangup_timer.done():
        hangup_timer.cancel()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point compatible with Pipecat runner and Pipecat Cloud."""
    body = runner_args.body or {}

    # Get room_url/token from DailyRunnerArguments or from body
    if isinstance(runner_args, DailyRunnerArguments):
        room_url = runner_args.room_url
        token = runner_args.token
    else:
        room_url = body.get("room_url")
        token = body.get("token")

    transport = DailyTransport(
        room_url,
        token,
        "American Dream Phone",
        DailyParams(
            api_url=os.getenv("DAILY_API_URL", "https://api.daily.co/v1"),
            api_key=os.getenv("DAILY_API_KEY", ""),
            audio_in_enabled=True,
            audio_out_enabled=True,
            video_out_enabled=False,
        ),
    )

    await run_bot(transport, runner_args.handle_sigint, body)


if __name__ == "__main__":
    # For standalone testing via pipecat runner (curl-based).
    # For the full app with frontend, use: uv run python server.py
    from pipecat.runner.run import main

    main()
