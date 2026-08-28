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

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from .config import settings
from .developer_keys import (
    DeveloperKeyStoreNotConfigured,
    MAX_DEVELOPER_NAME_LENGTH,
    build_developer_api_key_store,
)
from .engine import ChatterboxEngine
from .storage import VoiceStore

logger = logging.getLogger("chatterbox")

app = FastAPI(title="Chatterbox Voice Server", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
store = VoiceStore(settings.voice_dir)
engine = ChatterboxEngine(settings.device, settings.conditioning_cache_size)
developer_key_store = build_developer_api_key_store(settings)

WAV_EXT = {".wav"}
CONVERTIBLE_EXTS = {
    ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus",
    ".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v",
}


def _delete_generated_file(path: Path):
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Could not remove generated audio file %s", path.name, exc_info=True)


def _cleanup_old_generated_files() -> int:
    ttl_seconds = settings.generated_audio_ttl_seconds
    if ttl_seconds <= 0:
        return 0

    generated_dir = settings.generated_dir.resolve()
    if generated_dir == settings.voice_dir.resolve():
        logger.warning("Generated audio cleanup skipped because generated_dir equals voice_dir")
        return 0

    cutoff = datetime.now(timezone.utc).timestamp() - ttl_seconds
    removed = 0
    for path in generated_dir.glob("*.wav"):
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            logger.warning("Could not remove old generated audio file %s", path.name, exc_info=True)
    return removed


def _warm_engine():
    try:
        timings = engine.warmup()
        logger.info("engine warmup complete %s", _timings_header(timings))
    except ImportError:
        logger.warning("Chatterbox is not installed; skipping startup warmup")
    except Exception:
        logger.exception("Engine warmup failed")


def _ensure_developer_key_schema():
    try:
        developer_key_store.ensure_schema()
        logger.info("developer API key table is ready")
    except DeveloperKeyStoreNotConfigured:
        return
    except Exception:
        logger.exception("Developer API key table setup failed")


@app.on_event("startup")
async def warm_engine_on_startup():
    asyncio.get_running_loop().run_in_executor(None, _cleanup_old_generated_files)
    if settings.preload_model:
        asyncio.get_running_loop().run_in_executor(None, _warm_engine)
    if developer_key_store.configured:
        asyncio.get_running_loop().run_in_executor(None, _ensure_developer_key_schema)


class TTSRequest(BaseModel):
    voice_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1)


class DeveloperApiKeyCreateRequest(BaseModel):
    developer_name: str = Field(min_length=1, max_length=MAX_DEVELOPER_NAME_LENGTH)


def auth(authorization: str | None = Header(default=None)):
    if authorization != f"Bearer {settings.api_key}":
        raise HTTPException(401, "Invalid or missing API key")


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def developer_auth(authorization: str | None = Header(default=None)):
    token = _bearer_token(authorization)
    if token is None:
        raise HTTPException(401, "Invalid or missing API key")

    try:
        record = developer_key_store.authenticate(token)
    except DeveloperKeyStoreNotConfigured as exc:
        raise HTTPException(503, "Developer API key storage is not configured") from exc

    if record is None:
        raise HTTPException(401, "Invalid or revoked API key")
    return record


def _developer_store_or_503():
    try:
        developer_key_store.ensure_schema()
    except DeveloperKeyStoreNotConfigured as exc:
        raise HTTPException(503, "Developer API key storage is not configured") from exc


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


def _public_voice(voice: dict) -> dict:
    return {
        "voice_id": voice["voice_id"],
        "name": voice.get("display_name") or voice.get("name") or voice["voice_id"],
    }


def _synthesize_to_file(voice_id: str, text: str) -> tuple[Path, dict]:
    request_started_at = perf_counter()
    timings = {"request_received_ms": 0.0}
    _cleanup_old_generated_files()

    validation_started_at = perf_counter()
    if len(text) > settings.max_text_length:
        raise HTTPException(422, f"Text exceeds {settings.max_text_length} characters")
    timings["request_validation_ms"] = _elapsed_ms(validation_started_at)

    lookup_started_at = perf_counter()
    reference = store.path(voice_id)
    timings["voice_lookup_ms"] = _elapsed_ms(lookup_started_at)
    if reference is None:
        raise HTTPException(404, "Voice not found")

    output_started_at = perf_counter()
    output = settings.generated_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex}.wav"
    timings["output_path_ms"] = _elapsed_ms(output_started_at)

    try:
        timings.update(engine.synthesize(text, reference, output, cache_key=voice_id))
    except ImportError as exc:
        raise HTTPException(503, "Chatterbox is not installed (pip install chatterbox-tts)") from exc
    except Exception as exc:
        logger.exception("TTS generation failed for voice %s", voice_id)
        raise HTTPException(500, "TTS generation failed") from exc

    timings["total_request_ms"] = _elapsed_ms(request_started_at)
    timings["generated_file"] = output.name
    return output, timings


def _tts_file_response(output: Path, timings: dict, cleanup: bool = False) -> FileResponse:
    response_started_at = perf_counter()
    response = FileResponse(
        output,
        media_type="audio/wav",
        filename=output.name,
        background=BackgroundTask(_delete_generated_file, output) if cleanup else None,
    )
    timings["response_construction_ms"] = _elapsed_ms(response_started_at)
    response.headers["X-TTS-Timings"] = _timings_header(timings)
    response.headers["X-TTS-Total-Ms"] = str(timings["total_request_ms"])
    response.headers["X-TTS-Cache-Hit"] = "1" if timings.get("reference_cache_hit") else "0"
    return response


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
    engine_status = engine.status()
    return {
        "status": "ready" if engine_status["model_loaded"] else "warming_up",
        "api_status": "alive",
        "device": engine_status["device"],
        "model_loaded": engine_status["model_loaded"],
        "audio_io_loaded": engine_status["audio_io_loaded"],
        "engine": engine_status,
    }


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


@app.get("/api/developer-keys", dependencies=[Depends(auth)])
def list_developer_api_keys():
    _developer_store_or_503()
    return {"keys": [record.public() for record in developer_key_store.list()]}


@app.post("/api/developer-keys", dependencies=[Depends(auth)])
def create_developer_api_key(payload: DeveloperApiKeyCreateRequest):
    _developer_store_or_503()
    try:
        record, api_key = developer_key_store.create(payload.developer_name)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    body = record.public()
    body["api_key"] = api_key
    return body


@app.post("/api/developer-keys/{key_id}/revoke", dependencies=[Depends(auth)])
def revoke_developer_api_key(key_id: str):
    _developer_store_or_503()
    record = developer_key_store.revoke(key_id)
    if record is None:
        raise HTTPException(404, "Developer API key not found")
    return record.public()


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
    output, timings = _synthesize_to_file(payload.voice_id, payload.text)
    response = _tts_file_response(output, timings)
    logger.info("tts timings voice_id=%s %s", payload.voice_id, _timings_header(timings))
    return response


@app.get("/v1/voices", dependencies=[Depends(developer_auth)])
def developer_voices():
    return {"voices": [_public_voice(voice) for voice in store.list()]}


@app.post("/v1/audio/speech", dependencies=[Depends(developer_auth)])
def developer_tts(payload: TTSRequest):
    output, timings = _synthesize_to_file(payload.voice_id, payload.text)
    response = _tts_file_response(output, timings, cleanup=True)
    logger.info("developer tts timings voice_id=%s %s", payload.voice_id, _timings_header(timings))
    return response


@app.websocket("/v1/realtime")
async def realtime_voice(websocket: WebSocket):
    token = _bearer_token(websocket.headers.get("authorization"))
    if token is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        record = developer_key_store.authenticate(token)
    except DeveloperKeyStoreNotConfigured:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    if record is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    await websocket.send_json({"type": "session.ready"})

    session_voice_id: str | None = None
    sequence = 0

    while True:
        try:
            message = await websocket.receive_json()
        except WebSocketDisconnect:
            return
        except ValueError:
            await websocket.send_json({"type": "error", "detail": "Send JSON messages."})
            continue

        if not isinstance(message, dict):
            await websocket.send_json({"type": "error", "detail": "Send a JSON object."})
            continue

        message_type = message.get("type")

        if message_type == "session.configure":
            voice_id = message.get("voice_id")
            if not isinstance(voice_id, str) or not voice_id.strip():
                await websocket.send_json({"type": "error", "detail": "voice_id is required."})
                continue
            clean_voice_id = voice_id.strip()
            if store.path(clean_voice_id) is None:
                await websocket.send_json({"type": "error", "status": 404, "detail": "Voice not found"})
                continue
            session_voice_id = clean_voice_id
            await websocket.send_json({"type": "session.configured", "voice_id": session_voice_id})
            continue

        if message_type == "text":
            text = message.get("text")
            if not isinstance(text, str) or not text.strip():
                await websocket.send_json({"type": "error", "detail": "text is required."})
                continue

            active_voice_id = session_voice_id
            message_voice_id = message.get("voice_id")
            if isinstance(message_voice_id, str) and message_voice_id.strip():
                active_voice_id = message_voice_id.strip()

            if not active_voice_id:
                await websocket.send_json({"type": "error", "detail": "Configure a voice_id first."})
                continue

            sequence += 1
            segment_started_at = perf_counter()
            output: Path | None = None
            try:
                output, timings = await asyncio.to_thread(_synthesize_to_file, active_voice_id, text.strip())
                audio = await asyncio.to_thread(output.read_bytes)
            except HTTPException as exc:
                await websocket.send_json({"type": "error", "status": exc.status_code, "detail": exc.detail})
                continue
            finally:
                if output is not None:
                    await asyncio.to_thread(_delete_generated_file, output)

            await websocket.send_json({
                "type": "audio",
                "sequence": sequence,
                "voice_id": active_voice_id,
                "content_type": "audio/wav",
                "latency_ms": _elapsed_ms(segment_started_at),
                "timings": timings,
            })
            await websocket.send_bytes(audio)
            continue

        await websocket.send_json({"type": "error", "detail": "Unsupported message type."})
