import io
import json
import wave
from fastapi.testclient import TestClient
from app.main import app, store, engine

client = TestClient(app)
HEADERS = {"Authorization": "Bearer change-me"}

def wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000); f.writeframes(b"\0" * 480)
    return buf.getvalue()

def test_health_and_auth():
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/voices").status_code == 401

def test_upload_and_list():
    response = client.post(
        "/api/voices",
        headers=HEADERS,
        data={"display_name": "James"},
        files={"file": ("sample.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 200
    uploaded = response.json()
    assert uploaded["id"] == uploaded["voice_id"]
    assert uploaded["voice_id"].startswith("voice_")
    assert uploaded["display_name"] == "James"
    assert uploaded["preview_available"] is True

    list_response = client.get("/api/voices", headers=HEADERS)
    assert list_response.status_code == 200
    assert any(
        voice["voice_id"] == uploaded["voice_id"] and voice["display_name"] == "James"
        for voice in list_response.json()["voices"]
    )


def test_preview_returns_reference_audio():
    voice = store.save(wav_bytes())
    response = client.get(f"/api/voices/{voice['voice_id']}/preview", headers=HEADERS)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")

    traversal = client.get("/api/voices/../secret/preview", headers=HEADERS)
    assert traversal.status_code == 404

def test_delete_voice_removes_reference_metadata_and_cache():
    voice = store.save(wav_bytes(), display_name="Mistake")
    cache_key = f"{voice['voice_id']}:test"
    engine._conditioning_cache[cache_key] = object()

    response = client.delete(f"/api/voices/{voice['voice_id']}", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    assert response.json()["voice_id"] == voice["voice_id"]
    assert response.json()["cache_entries_removed"] == 1
    assert cache_key not in engine._conditioning_cache

    list_response = client.get("/api/voices", headers=HEADERS)
    assert all(item["voice_id"] != voice["voice_id"] for item in list_response.json()["voices"])
    assert client.get(f"/api/voices/{voice['voice_id']}/preview", headers=HEADERS).status_code == 404
    assert client.delete(f"/api/voices/{voice['voice_id']}", headers=HEADERS).status_code == 404

def test_rejects_non_wav_and_missing_voice():
    assert client.post("/api/voices", headers=HEADERS, files={"file": ("sample.txt", b"x", "text/plain")}).status_code == 415
    assert client.post("/api/tts", headers=HEADERS, json={"voice_id": "../secret", "text": "Hi"}).status_code == 404

def test_video_upload_accepted_but_needs_ffmpeg():
    # A .mp4 upload is accepted by the extension allow-list; conversion fails
    # cleanly (400) when ffmpeg is unavailable or the file is not real video.
    response = client.post("/api/voices", headers=HEADERS, files={"file": ("clip.mp4", b"not a real video", "video/mp4")})
    assert response.status_code == 400

def test_fix_wav_header_patches_pipe_sizes():
    # ffmpeg emits 0xFFFFFFFF size fields when streaming WAV to stdout;
    # _fix_wav_header must patch them so parsers read the true frame count.
    from app.main import _fix_wav_header
    bad = bytearray(wav_bytes())
    bad[4:8] = b"\xff\xff\xff\xff"  # RIFF size
    bad[-9:-5] = b"\xff\xff\xff\xff"  # data chunk size (44-byte header wav)
    fixed = _fix_wav_header(bytes(bad))
    assert fixed[4:8] != b"\xff\xff\xff\xff"
    assert int.from_bytes(fixed[4:8], "little") == len(fixed) - 8
    with wave.open(io.BytesIO(fixed)) as f:
        assert f.getnframes() == 240  # 480 bytes / 2 bytes-per-frame

def test_upload_rejects_wrong_api_key():
    response = client.post(
        "/api/voices",
        headers={"Authorization": "Bearer wrong-key"},
        files={"file": ("sample.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 401


def test_tts_returns_wav_and_safe_timing_headers(monkeypatch):
    voice = store.save(wav_bytes())

    def fake_synthesize(text, reference, output, cache_key=None):
        output.write_bytes(wav_bytes())
        return {
            "lock_wait_ms": 0.0,
            "model_was_warm": True,
            "model_load_ms": 0.0,
            "reference_cache_lookup_ms": 0.0,
            "reference_cache_hit": True,
            "reference_decode_condition_ms": 0.0,
            "gpu_inference_ms": 1.0,
            "wav_encoding_ms": 1.0,
            "conditioning_cache_size": 1,
            "engine_total_ms": 2.0,
        }

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)
    response = client.post(
        "/api/tts",
        headers=HEADERS,
        json={"voice_id": voice["voice_id"], "text": "Hi"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["x-tts-cache-hit"] == "1"
    timings = json.loads(response.headers["x-tts-timings"])
    assert timings["reference_cache_hit"] is True
    assert timings["gpu_inference_ms"] == 1.0
    assert "generated_file" in timings
