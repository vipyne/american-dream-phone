"""services.py — STT/TTS/LLM factories, the only place service classes are built.

Online (default): Deepgram STT, Cartesia TTS, Anthropic LLM.
OFFLINE=true:     Whisper-MLX STT, Kokoro TTS, Ollama LLM (all local).

Each branch imports its services lazily, so online mode never imports
mlx/kokoro and offline mode never needs cloud API keys.
"""

import offline_config  # must precede any pipecat import (sets HF_HOME etc.)

import os

from pipecat.services.llm_service import LLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService


def create_stt() -> STTService:
    if offline_config.OFFLINE:
        from pipecat.services.whisper.stt import MLXModel, WhisperSTTServiceMLX

        return WhisperSTTServiceMLX(
            settings=WhisperSTTServiceMLX.Settings(
                model=MLXModel[offline_config.whisper_model()],
            )
        )

    from pipecat.services.deepgram.stt import DeepgramSTTService

    return DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY"))


def create_tts() -> TTSService:
    if offline_config.OFFLINE:
        from pipecat.services.kokoro.tts import KokoroTTSService

        from spoken_text_filter import SpokenTextFilter

        return KokoroTTSService(
            settings=KokoroTTSService.Settings(voice=offline_config.kokoro_voice()),
            model_path=offline_config.kokoro_model_path(),
            voices_path=offline_config.kokoro_voices_path(),
            text_filters=[SpokenTextFilter()],
        )

    from pipecat.services.cartesia.tts import CartesiaTTSService

    return CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY", ""),
        settings=CartesiaTTSService.Settings(
            voice="b7d50908-b17c-442d-ad8d-810c63997ed9",  # Helpful Woman
        ),
    )


def create_llm() -> LLMService:
    if offline_config.OFFLINE:
        from pipecat.services.ollama.llm import OLLamaLLMService

        return OLLamaLLMService(
            settings=OLLamaLLMService.Settings(model=offline_config.llm_model()),
            base_url=offline_config.ollama_base_url(),
        )

    from pipecat.services.anthropic.llm import AnthropicLLMService

    return AnthropicLLMService(
        api_key=os.getenv("ANTHROPIC_API_KEY"),
        settings=AnthropicLLMService.Settings(
            model="claude-sonnet-4-6",
        ),
    )
