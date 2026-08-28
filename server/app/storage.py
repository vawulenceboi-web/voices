import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

class VoiceStore:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.metadata_path = self.directory / "voice_metadata.json"
        self._display_names = self._load_metadata()

    def _load_metadata(self) -> dict[str, str]:
        if not self.metadata_path.is_file():
            return {}
        try:
            data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        voices = data.get("voices") if isinstance(data, dict) else None
        if not isinstance(voices, dict):
            return {}
        names: dict[str, str] = {}
        for voice_id, display_name in voices.items():
            if not isinstance(voice_id, str) or not isinstance(display_name, str):
                continue
            clean_voice_id = voice_id.strip()
            clean_display_name = self._clean_display_name(display_name)
            if clean_voice_id and clean_display_name:
                names[clean_voice_id] = clean_display_name
        return names

    def _write_metadata(self):
        tmp_path = self.metadata_path.with_suffix(".json.tmp")
        payload = {"voices": self._display_names}
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.metadata_path)

    def _clean_display_name(self, display_name: str | None) -> str:
        return " ".join((display_name or "").split())[:80]

    def _metadata(self, path: Path) -> dict:
        stat = path.stat()
        voice_id = path.stem
        created_at = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
        return {
            "id": voice_id,
            "voice_id": voice_id,
            "name": self._display_name(voice_id),
            "display_name": self._display_name(voice_id),
            "filename": path.name,
            "size_bytes": stat.st_size,
            "created_at": created_at,
            "updated_at": created_at,
            "preview_available": True,
        }

    def _display_name(self, voice_id: str) -> str:
        stored = self._display_names.get(voice_id)
        if stored:
            return stored
        if voice_id.startswith("voice_"):
            suffix = voice_id.removeprefix("voice_").upper()
            return f"Voice {suffix[:4]} {suffix[4:]}".strip()
        return voice_id.replace("_", " ").replace("-", " ").title()

    def list(self):
        return [self._metadata(p) for p in sorted(self.directory.glob("*.wav"))]

    def path(self, voice_id: str) -> Path | None:
        if not voice_id or Path(voice_id).name != voice_id or voice_id != Path(voice_id).stem:
            return None
        path = (self.directory / f"{voice_id}.wav").resolve()
        return path if path.parent == self.directory and path.is_file() else None

    def save(self, data: bytes, display_name: str | None = None) -> dict:
        voice_id = f"voice_{uuid4().hex[:10]}"
        path = self.directory / f"{voice_id}.wav"
        path.write_bytes(data)
        clean_display_name = self._clean_display_name(display_name)
        if clean_display_name:
            self._display_names[voice_id] = clean_display_name
            self._write_metadata()
        return self._metadata(path)

    def delete(self, voice_id: str) -> dict | None:
        path = self.path(voice_id)
        if path is None:
            return None
        path.unlink()
        had_display_name = self._display_names.pop(voice_id, None) is not None
        if had_display_name or self.metadata_path.is_file():
            self._write_metadata()
        return {"voice_id": voice_id, "deleted": True}
