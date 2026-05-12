"""
Local voice transcription via faster-whisper.

Model is loaded once (singleton) on first call and cached in memory.
Audio is recorded with sounddevice at 16 kHz mono float32.

Optional dependencies (add to pyproject.toml [voice] group):
  faster-whisper>=1.0.0
  sounddevice>=0.4.6
  numpy>=1.24

If these packages are not installed, all public functions raise ImportError
with a clear message — callers should handle gracefully.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Literal

logger = logging.getLogger("vanilla.voice")

ModelSize = Literal["tiny", "base", "small", "medium"]

# Singleton WhisperModel — loaded once on first transcription call
_model = None
_model_size: ModelSize = "base"

# Start/stop recording state — supports hold-to-talk and button-toggle patterns
_record_stream = None
_record_frames: list = []
_record_model_size: ModelSize = "base"
_record_lock = threading.Lock()


def get_model(size: ModelSize = "base"):
    """Load (or return cached) WhisperModel. Downloads on first call (~150MB for 'base')."""
    global _model, _model_size
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        raise ImportError(
            "faster-whisper is not installed. "
            "Run: pip install faster-whisper"
        )

    if _model is None or _model_size != size:
        logger.info("Loading WhisperModel (%s)…", size)
        _model = WhisperModel(size, device="cpu", compute_type="int8")
        _model_size = size
        logger.info("WhisperModel loaded.")

    return _model


async def record_audio(duration_s: float) -> "np.ndarray":
    """Record audio from the default microphone for duration_s seconds."""
    try:
        import numpy as np  # type: ignore
        import sounddevice as sd  # type: ignore
    except ImportError:
        raise ImportError(
            "sounddevice and numpy are required for voice recording. "
            "Run: pip install sounddevice numpy"
        )

    sample_rate = 16_000
    num_samples = int(duration_s * sample_rate)

    loop = asyncio.get_event_loop()

    def _record():
        audio = sd.rec(
            num_samples,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()
        return audio.squeeze()  # (N,) float32

    return await loop.run_in_executor(None, _record)


async def transcribe(audio: "np.ndarray", model_size: ModelSize = "base") -> str:
    """
    Transcribe a numpy audio array (16 kHz mono float32) using faster-whisper.
    Returns the transcript string.
    """
    try:
        import numpy as np  # type: ignore
    except ImportError:
        raise ImportError("numpy is required. Run: pip install numpy")

    model = get_model(model_size)

    loop = asyncio.get_event_loop()

    def _transcribe():
        segments, _ = model.transcribe(audio, beam_size=5, language=None)
        return " ".join(seg.text.strip() for seg in segments).strip()

    return await loop.run_in_executor(None, _transcribe)


def start_recording(model_size: ModelSize = "base") -> None:
    """
    Start capturing audio from the default microphone in the background.
    Call stop_recording_and_transcribe() to finalise and get the transcript.
    Thread-safe: stops any in-progress recording before starting a new one.
    """
    global _record_stream, _record_frames, _record_model_size
    try:
        import sounddevice as sd  # type: ignore
    except ImportError:
        raise ImportError(
            "sounddevice is required for voice recording. "
            "Run: pip install sounddevice"
        )

    with _record_lock:
        # Stop any existing recording cleanly before starting a new one
        if _record_stream is not None:
            try:
                _record_stream.stop()
                _record_stream.close()
            except Exception:
                pass
            _record_stream = None

        _record_frames = []
        _record_model_size = model_size

        def _callback(indata, frames, time_info, status):
            _record_frames.append(indata.copy())

        _record_stream = sd.InputStream(
            samplerate=16_000,
            channels=1,
            dtype="float32",
            callback=_callback,
        )
        _record_stream.start()
        logger.info("Recording started (model=%s)", model_size)


async def stop_recording_and_transcribe() -> tuple[str, int]:
    """
    Stop the active recording and transcribe the captured audio.
    Returns (transcript, duration_ms).
    Raises RuntimeError if no recording is active.
    """
    global _record_stream, _record_frames
    import time

    try:
        import numpy as np  # type: ignore
    except ImportError:
        raise ImportError("numpy is required. Run: pip install numpy")

    start = time.monotonic()

    with _record_lock:
        stream = _record_stream
        frames = list(_record_frames)
        model_size = _record_model_size
        _record_stream = None
        _record_frames = []

    if stream is None:
        raise RuntimeError("No active recording — call start_recording() first")

    try:
        stream.stop()
        stream.close()
    except Exception as e:
        logger.warning("Error closing recording stream: %s", e)

    if not frames:
        logger.warning("No audio frames captured")
        return "", 0

    audio = np.concatenate(frames, axis=0).squeeze()
    duration_captured = len(audio) / 16_000
    logger.info("Captured %.2fs of audio (%d frames)", duration_captured, len(frames))

    transcript = await transcribe(audio, model_size=model_size)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info("Transcribed in %dms: %r", elapsed_ms, transcript[:80])
    return transcript, elapsed_ms


async def record_and_transcribe(
    duration_s: float,
    model_size: ModelSize = "base",
) -> tuple[str, int]:
    """
    Record audio then transcribe it.
    Returns (transcript, duration_ms).
    """
    import time

    start = time.monotonic()
    audio = await record_audio(duration_s)
    transcript = await transcribe(audio, model_size=model_size)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    logger.info(
        "Transcribed %.1fs of audio in %dms: %r",
        duration_s,
        elapsed_ms,
        transcript[:80],
    )
    return transcript, elapsed_ms


def list_available_models() -> list[dict]:
    """
    Return info about supported model sizes and whether they are cached locally.
    Requires huggingface_hub for cache inspection; falls back to unknown.
    """
    sizes: list[ModelSize] = ["tiny", "base", "small", "medium"]
    result = []

    for size in sizes:
        downloaded = False
        try:
            from huggingface_hub import scan_cache_dir  # type: ignore

            cache = scan_cache_dir()
            model_id = f"Systran/faster-whisper-{size}"
            for repo in cache.repos:
                if repo.repo_id == model_id:
                    downloaded = True
                    break
        except Exception:
            pass

        result.append({"size": size, "downloaded": downloaded})

    return result
