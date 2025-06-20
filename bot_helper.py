import json

from pipecat.frames.frames import (
    EndFrame,
    EndTaskFrame,
    InputAudioRawFrame,
    StopTaskFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)

from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from typing import Any, Dict, List, Optional


class UserAudioCollector(FrameProcessor):
    """Collects audio frames in a buffer, then adds them to the LLM context when the user stops speaking."""

    def __init__(self, context, user_context_aggregator):
        super().__init__()
        self._context = context
        self._user_context_aggregator = user_context_aggregator
        self._audio_frames = []
        self._start_secs = 0.2  # this should match VAD start_secs (hardcoding for now)
        self._user_speaking = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            # Skip transcription frames - we're handling audio directly
            return
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            self._context.add_audio_frames_message(audio_frames=self._audio_frames)
            await self._user_context_aggregator.push_frame(
                self._user_context_aggregator.get_context_frame()
            )
        elif isinstance(frame, InputAudioRawFrame):
            if self._user_speaking:
                # When speaking, collect frames
                self._audio_frames.append(frame)
            else:
                # Maintain a rolling buffer of recent audio (for start of speech)
                self._audio_frames.append(frame)
                frame_duration = (
                    len(frame.audio) / 16 * frame.num_channels / frame.sample_rate
                )
                buffer_duration = frame_duration * len(self._audio_frames)
                while buffer_duration > self._start_secs:
                    self._audio_frames.pop(0)
                    buffer_duration -= frame_duration

        await self.push_frame(frame, direction)


class DialOutHelper:
    def __init__(self, body):
        super().__init__()

        self._body = json.loads(body)

    async def start_dialout(self, transport, dialout_settings=None):
        """Helper function to start dialout using the provided settings or from body.

        Args:
            transport: The transport instance to use for dialout
            dialout_settings: Optional override for dialout settings

        Returns:
            None
        """
        # Use provided settings or get from body
        settings = dialout_settings or self.get_dialout_settings()
        if not settings:
            print("No dialout settings available")
            return

        for setting in settings:
            if "phoneNumber" in setting:
                print(f"Dialing number: {setting['phoneNumber']}")
                if "callerId" in setting:
                    print(f"with callerId: {setting['callerId']}")
                    await transport.start_dialout(
                        {
                            "phoneNumber": setting["phoneNumber"],
                            "callerId": setting["callerId"],
                        }
                    )
                else:
                    print("with no callerId")
                    await transport.start_dialout(
                        {"phoneNumber": setting["phoneNumber"]}
                    )
            elif "sipUri" in setting:
                print(f"Dialing sipUri: {setting['sipUri']}")
                await transport.start_dialout({"sipUri": setting["sipUri"]})
            else:
                print(f"Unknown dialout setting format: {setting}")

    def get_dialout_settings(self) -> Optional[List[Dict[str, Any]]]:
        """Extract dialout settings from the body.

        Returns:
            List of dialout setting objects or None if not present
        """
        # Check if we have dialout settings
        if "dialout_settings" in self._body:
            dialout_settings = self._body["dialout_settings"]

            # Convert to list if it's an object (for backward compatibility)
            if isinstance(dialout_settings, dict):
                return [dialout_settings]
            elif isinstance(dialout_settings, list):
                return dialout_settings

        return None

    def get_is_test_mode(self) -> Optional[List[Dict[str, Any]]]:
        print(f"_____bot_helper.py * self._body: {self._body}")
        test_mode = False
        if "testInPrebuilt" in self._body:
            test_mode = True
        print(f"_____bot_helper.py * test_mode: {test_mode}")

        return test_mode
