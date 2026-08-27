from pathlib import Path
from uuid import uuid4

class VoiceStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def list(self):
        return [{"voice_id": p.stem, "filename": p.name, "size_bytes": p.stat().st_size} for p in sorted(self.directory.glob("*.wav"))]

    def path(self, voice_id: str) -> Path | None:
        if not voice_id or Path(voice_id).name != voice_id or voice_id != Path(voice_id).stem:
            return None
        path = (self.directory / f"{voice_id}.wav").resolve()
        return path if path.parent == self.directory.resolve() and path.is_file() else None

    def save(self, data: bytes) -> dict:
        voice_id = f"voice_{uuid4().hex[:10]}"
        path = self.directory / f"{voice_id}.wav"
        path.write_bytes(data)
        return {"voice_id": voice_id, "filename": path.name, "size_bytes": len(data)}
