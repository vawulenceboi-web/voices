import asyncio
import json
import logging
import shutil
import wave
from asyncio.subprocess import PIPE
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import settings
from .engine import ChatterboxEngine
from .storage import VoiceStore

logger = logging.getLogger("chatterbox")

app = FastAPI(title="Chatterbox Voice Server", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)
store = VoiceStore(settings.voice_dir)
engine = ChatterboxEngine(settings.device, settings.conditioning_cache_size)

WAV_EXT = {".wav"}
CONVERTIBLE_EXTS = {
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus",
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v",
}


def _warm_engine():
    try:
        timings = engine.warmup()
        logger.info("engine warmup complete %s", _timings_header(timings))
    except ImportError:
        logger.warning("Chatterbox is not installed; skipping startup warmup")
    except Exception:
        logger.exception("Engine warmup failed")


@app.on_event("startup")
async def warm_engine_on_startup():
    if settings.preload_model:
        asyncio.get_running_loop().run_in_executor(None, _warm_engine)


class TTSRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1)


def auth(authorization: str | None = Header(default=None)):
    if authorization != f"Bearer {settings.api_key}":
        raise HTTPException(401, "Invalid or missing API key")


def valid_wav(data: bytes) -> bool:
    try:
        with wave.open(BytesIO(data)) as audio:
            return audio.getnchannels() > 0 and audio.getframerate() > 0
    except (wave.Error, EOFError):
        return False


def _fix_wav_header(data: bytes) -> bytes:
    """Patch RIFF/data size fields that ffmpeg leaves as 0xFFFFFFFF when streaming to a pipe.

    ffmpeg cannot seek back when writing WAV to stdout, so it emits size 0xFFFFFFFF;
    strict parsers (e.g. Python's wave module) then misreport the number of frames.
    """
    if data[:4] != b"RIFF" or len(data) < 44:
        return data
    out = bytearray(data)
    out[4:8] = (len(data) - 8).to_bytes(4, "little")
    i = 12
    while i + 8 <= len(data):
        cid = data[i:i + 4]
        csz = int.from_bytes(data[i + 4:i + 8], "little")
        if cid == b"data":
            out[i + 4:i + 8] = (len(data) - i - 8).to_bytes(4, "little")
            break
        i += 8 + csz + (csz & 1)
    return bytes(out)


def _ffmpeg_exe() -> str | None:
    """Locate ffmpeg: system PATH first, then the imageio-ffmpeg static binary."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)


def _timings_header(timings: dict) -> str:
    return json.dumps(timings, separators=(",", ":"), sort_keys=True)


async def convert_to_wav(data: bytes, suffix: str) -> bytes | None:
    """Convert any audio/video upload into a mono 24 kHz WAV via ffmpeg."""
    ffmpeg = _ffmpeg_exe()
    if ffmpeg is None:
        raise HTTPException(
            400,
            "ffmpeg is not installed; install it to upload video/audio references, or upload a .wav file instead",
        )
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
        "-vn", "-ac", "1", "-ar", "24000",
        "-t", str(settings.max_reference_seconds),
        "-f", "wav", "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=PIPE, stdout=PIPE, stderr=PIPE
        )
        out, err = await proc.communicate(data)
    except Exception:
        logger.exception("ffmpeg failed to start")
        return None
    if proc.returncode != 0 or not out:
        logger.warning("ffmpeg conversion failed (%s): %s", suffix, err.decode(errors="replace"))
        return None
    return _fix_wav_header(out)


@app.get("/", dependencies=[Depends(auth)])
def root():
    return {"service": "chatterbox-voice-server", "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "engine": engine.status()}


@app.get("/api/voices", dependencies=[Depends(auth)])
def voices():
    return {"voices": store.list()}


@app.get("/api/voices/{voice_id}/preview", dependencies=[Depends(auth)])
def preview_voice(voice_id: str):
    reference = store.path(voice_id)
    if reference is None:
        raise HTTPException(404, "Voice not found")
    return FileResponse(reference, media_type="audio/wav", filename=reference.name)


@app.delete("/api/voices/{voice_id}", dependencies=[Depends(auth)])
def delete_voice(voice_id: str):
    deleted = store.delete(voice_id)
    if deleted is None:
        raise HTTPException(404, "Voice not found")
    deleted["cache_entries_removed"] = engine.evict_voice(voice_id)
    return deleted


@app.post("/api/voices", dependencies=[Depends(auth)])
async def upload_voice(
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None),
    name: str | None = Form(default=None),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in WAV_EXT | CONVERTIBLE_EXTS:
        raise HTTPException(415, "Unsupported file type; use WAV, audio (mp3/m4a/aac/flac/ogg/opus) or video (mp4/mov/webm/mkv/avi/m4v)")

    limit = settings.max_reference_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, "Reference audio exceeds the configured size limit")

    if suffix == ".wav":
        wav = data
    else:
        wav = await convert_to_wav(data, suffix)
        if wav is None:
            raise HTTPException(400, "Could not extract audio from the uploaded file; upload a clean WAV reference instead")

    if not valid_wav(wav):
        raise HTTPException(400, "Uploaded file is not a valid WAV")
    return store.save(wav, display_name=display_name or name)


@app.post("/api/tts", dependencies=[Depends(auth)])
def tts(payload: TTSRequest):
    request_started_at = perf_counter()
    timings = {"request_received_ms": 0.0}

    validation_started_at = perf_counter()
    if len(payload.text) > settings.max_text_length:
        raise HTTPException(422, f"Text exceeds {settings.max_text_length} characters")
    timings["request_validation_ms"] = _elapsed_ms(validation_started_at)

    lookup_started_at = perf_counter()
    reference = store.path(payload.voice_id)
    timings["voice_lookup_ms"] = _elapsed_ms(lookup_started_at)
    if reference is None:
        raise HTTPException(404, "Voice not found")

    output_started_at = perf_counter()
    output = settings.generated_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex}.wav"
    timings["output_path_ms"] = _elapsed_ms(output_started_at)

    try:
        timings.update(engine.synthesize(payload.text, reference, output, cache_key=payload.voice_id))
    except ImportError as exc:
        raise HTTPException(503, "Chatterbox is not installed (pip install chatterbox-tts)") from exc
    except Exception as exc:
        logger.exception("TTS generation failed for voice %s", payload.voice_id)
        raise HTTPException(500, "TTS generation failed") from exc

    response_started_at = perf_counter()
    response = FileResponse(output, media_type="audio/wav", filename=output.name)
    timings["response_construction_ms"] = _elapsed_ms(response_started_at)
    timings["total_request_ms"] = _elapsed_ms(request_started_at)
    timings["generated_file"] = output.name
    response.headers["X-TTS-Timings"] = _timings_header(timings)
    response.headers["X-TTS-Total-Ms"] = str(timings["total_request_ms"])
    response.headers["X-TTS-Cache-Hit"] = "1" if timings.get("reference_cache_hit") else "0"
    logger.info("tts timings voice_id=%s %s", payload.voice_id, _timings_header(timings))
    return response
