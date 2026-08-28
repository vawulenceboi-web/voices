import io
import json
import os
import wave
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from app import main as main_module
from app.developer_keys import DeveloperApiKeyRecord, KEY_PREFIX
from app.main import app, store, engine

client = TestClient(app)
HEADERS = {"Authorization": "Bearer change-me"}


class FakeDeveloperApiKeyStore:
    configured = True

    def __init__(self):
        self.records: dict[str, DeveloperApiKeyRecord] = {}
        self.raw_to_id: dict[str, str] = {}
        self.counter = 0

    def ensure_schema(self):
        return None

    def create(self, developer_name: str):
        self.counter += 1
        key_id = f"00000000-0000-0000-0000-{self.counter:012d}"
        api_key = f"{KEY_PREFIX}test_key_{self.counter:04d}"
        record = DeveloperApiKeyRecord(
            id=key_id,
            developer_name=" ".join(developer_name.split()),
            key_prefix=KEY_PREFIX,
            key_last4=api_key[-4:],
            active=True,
            created_at=datetime.now(timezone.utc).isoformat(),
            revoked_at=None,
        )
        self.records[key_id] = record
        self.raw_to_id[api_key] = key_id
        return record, api_key

    def list(self):
        return list(reversed(list(self.records.values())))

    def revoke(self, key_id: str):
        record = self.records.get(key_id)
        if record is None:
            return None
        revoked = DeveloperApiKeyRecord(
            id=record.id,
            developer_name=record.developer_name,
            key_prefix=record.key_prefix,
            key_last4=record.key_last4,
            active=False,
            created_at=record.created_at,
            revoked_at=datetime.now(timezone.utc).isoformat(),
        )
        self.records[key_id] = revoked
        return revoked

    def authenticate(self, api_key: str):
        key_id = self.raw_to_id.get(api_key)
        if not key_id:
            return None
        record = self.records[key_id]
        return record if record.active else None


@pytest.fixture
def developer_key_store(monkeypatch):
    fake = FakeDeveloperApiKeyStore()
    monkeypatch.setattr(main_module, "developer_key_store", fake)
    return fake


@pytest.fixture(autouse=True)
def isolate_runtime_dirs(tmp_path):
    voice_dir = tmp_path / "voices"
    generated_dir = tmp_path / "generated"
    voice_dir.mkdir()
    generated_dir.mkdir()

    original_voice_dir = store.directory
    original_metadata_path = store.metadata_path
    original_display_names = store._display_names
    original_generated_dir = main_module.settings.generated_dir

    store.directory = voice_dir.resolve()
    store.metadata_path = store.directory / "voice_metadata.json"
    store._display_names = {}
    main_module.settings.generated_dir = generated_dir.resolve()
    engine._conditioning_cache.clear()

    yield

    store.directory = original_voice_dir
    store.metadata_path = original_metadata_path
    store._display_names = original_display_names
    main_module.settings.generated_dir = original_generated_dir
    engine._conditioning_cache.clear()

def wav_bytes():
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(24000); f.writeframes(b"\0" * 480)
    return buf.getvalue()

def test_health_and_auth():
    health = client.get("/health").json()
    assert health["api_status"] == "alive"
    assert health["status"] in {"warming_up", "ready"}
    assert health["device"] == engine.device
    assert health["model_loaded"] is False
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
    assert (main_module.settings.generated_dir / timings["generated_file"]).is_file()


def test_cleanup_old_generated_audio_only_touches_generated_dir(monkeypatch):
    old_generated = main_module.settings.generated_dir / "old.wav"
    new_generated = main_module.settings.generated_dir / "new.wav"
    old_voice_reference = store.directory / "old.wav"
    old_generated.write_bytes(wav_bytes())
    new_generated.write_bytes(wav_bytes())
    old_voice_reference.write_bytes(wav_bytes())

    expired = datetime.now(timezone.utc).timestamp() - 7200
    os.utime(old_generated, (expired, expired))
    os.utime(old_voice_reference, (expired, expired))
    monkeypatch.setattr(main_module.settings, "generated_audio_ttl_seconds", 3600)

    assert main_module._cleanup_old_generated_files() == 1
    assert not old_generated.exists()
    assert new_generated.is_file()
    assert old_voice_reference.is_file()


def create_developer_key():
    response = client.post(
        "/api/developer-keys",
        headers=HEADERS,
        json={"developer_name": " Acme Sales Bot "},
    )
    assert response.status_code == 200
    return response.json()


def test_developer_key_admin_create_list_and_revoke(developer_key_store):
    assert client.get("/api/developer-keys").status_code == 401

    created = create_developer_key()
    assert created["developer_name"] == "Acme Sales Bot"
    assert created["api_key"].startswith(KEY_PREFIX)
    assert created["masked_key"].startswith(KEY_PREFIX)
    assert created["masked_key"].endswith(created["api_key"][-4:])
    assert created["active"] is True

    list_response = client.get("/api/developer-keys", headers=HEADERS)
    assert list_response.status_code == 200
    listed = list_response.json()["keys"][0]
    assert listed["id"] == created["id"]
    assert listed["masked_key"] == created["masked_key"]
    assert "api_key" not in listed

    valid_headers = {"Authorization": f"Bearer {created['api_key']}"}
    assert client.get("/v1/voices", headers=valid_headers).status_code == 200

    revoke_response = client.post(
        f"/api/developer-keys/{created['id']}/revoke",
        headers=HEADERS,
    )
    assert revoke_response.status_code == 200
    assert revoke_response.json()["active"] is False
    assert client.get("/v1/voices", headers=valid_headers).status_code == 401


def test_developer_voices_require_active_bearer_key(developer_key_store):
    voice = store.save(wav_bytes(), display_name="Sarah")
    created = create_developer_key()

    assert client.get("/v1/voices").status_code == 401
    assert client.get("/v1/voices", headers={"Authorization": "Bearer wrong"}).status_code == 401

    response = client.get(
        "/v1/voices",
        headers={"Authorization": f"Bearer {created['api_key']}"},
    )
    assert response.status_code == 200
    assert {"voice_id": voice["voice_id"], "name": "Sarah"} in response.json()["voices"]
    assert all(set(item.keys()) == {"voice_id", "name"} for item in response.json()["voices"])


def test_developer_speech_uses_selected_voice_id(monkeypatch, developer_key_store):
    voice = store.save(wav_bytes(), display_name="Bot Voice")
    created = create_developer_key()
    calls = []

    def fake_synthesize(text, reference, output, cache_key=None):
        calls.append({"text": text, "reference": reference, "cache_key": cache_key})
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
        "/v1/audio/speech",
        headers={"Authorization": f"Bearer {created['api_key']}"},
        json={"voice_id": voice["voice_id"], "text": "Hello"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content.startswith(b"RIFF")
    assert list(main_module.settings.generated_dir.glob("*.wav")) == []
    assert calls == [{
        "text": "Hello",
        "reference": store.path(voice["voice_id"]),
        "cache_key": voice["voice_id"],
    }]


def test_realtime_uses_same_developer_key_and_segmented_tts(monkeypatch, developer_key_store):
    voice = store.save(wav_bytes(), display_name="Live Voice")
    created = create_developer_key()
    calls = []

    def fake_synthesize(text, reference, output, cache_key=None):
        calls.append({"text": text, "reference": reference, "cache_key": cache_key})
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

    with client.websocket_connect(
        "/v1/realtime",
        headers={"Authorization": f"Bearer {created['api_key']}"},
    ) as websocket:
        assert websocket.receive_json()["type"] == "session.ready"

        websocket.send_json({"type": "session.configure", "voice_id": voice["voice_id"]})
        assert websocket.receive_json() == {
            "type": "session.configured",
            "voice_id": voice["voice_id"],
        }

        websocket.send_json({"type": "text", "text": "Thanks for calling."})
        meta = websocket.receive_json()
        audio = websocket.receive_bytes()

    assert meta["type"] == "audio"
    assert meta["voice_id"] == voice["voice_id"]
    assert meta["content_type"] == "audio/wav"
    assert meta["timings"]["reference_cache_hit"] is True
    assert audio.startswith(b"RIFF")
    assert list(main_module.settings.generated_dir.glob("*.wav")) == []
    assert calls == [{
        "text": "Thanks for calling.",
        "reference": store.path(voice["voice_id"]),
        "cache_key": voice["voice_id"],
    }]
