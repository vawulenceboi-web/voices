import io
import wave
from fastapi.testclient import TestClient
from app.main import app, store, engine

client = TestClient(app)
HEADERS = {"Authorization": "Bearer change-me"}

def wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000); f.writeframes(b"\\0" * 480)
    return buf.getvalue()

def test_health_and_auth():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/voices").status_code == 401

def test_upload_and_list():
    response = client.post("/api/voices", headers=HEADERS, files={"file": ("sample.wav", wav_bytes(), "audio/wav")})
    assert response.status_code == 200
    assert response.json()["voice_id"].startswith("voice_")
    assert client.get("/api/voices", headers=HEADERS).status_code == 200

def test_rejects_non_wav_and_missing_voice():
    assert client.post("/api/voices", headers=HEADERS, files={"file": ("sample.txt", b"x", "text/plain")}).status_code == 415
    assert client.post("/api/tts", headers=HEADERS, json={"voice_id": "../secret", "text": "Hi"}).status_code == 404
