from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
import wave
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .config import settings
from .engine import ChatterboxEngine
from .storage import VoiceStore

app = FastAPI(title="Chatterbox Voice Server", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
store = VoiceStore(settings.voice_dir)
engine = ChatterboxEngine(settings.device)

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

@app.get("/", dependencies=[Depends(auth)])
def root():
    return {"service": "chatterbox-voice-server", "status": "ok"}

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/voices", dependencies=[Depends(auth)])
def voices():
    return {"voices": store.list()}

@app.post("/api/voices", dependencies=[Depends(auth)])
async def upload_voice(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() != ".wav":
        raise HTTPException(415, "Only WAV reference audio is supported")
    data = await file.read(settings.max_reference_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_reference_mb * 1024 * 1024:
        raise HTTPException(413, "Reference audio exceeds the configured size limit")
    if not valid_wav(data):
        raise HTTPException(400, "Uploaded file is not a valid WAV")
    return store.save(data)

@app.post("/api/tts", dependencies=[Depends(auth)])
def tts(payload: TTSRequest):
    if len(payload.text) > settings.max_text_length:
        raise HTTPException(422, f"Text exceeds {settings.max_text_length} characters")
    reference = store.path(payload.voice_id)
    if reference is None:
        raise HTTPException(404, "Voice not found")
    output = settings.generated_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex}.wav"
    try:
        engine.synthesize(payload.text, reference, output)
    except ImportError as exc:
        raise HTTPException(503, "Chatterbox is not installed") from exc
    return FileResponse(output, media_type="audio/wav", filename=output.name)
