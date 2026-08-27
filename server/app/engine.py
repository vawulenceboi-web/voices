from pathlib import Path
from threading import Lock

class ChatterboxEngine:
    """Lazy, single-process boundary around Chatterbox."""
    def __init__(self, device: str):
        self.device = device
        self._model = None
        self._lock = Lock()

    def _load(self):
        if self._model is None:
            from chatterbox.tts import ChatterboxTTS
            self._model = ChatterboxTTS.from_pretrained(device=self.device)
        return self._model

    def synthesize(self, text: str, reference: Path, output: Path) -> Path:
        import torchaudio
        with self._lock:
            wav = self._load().generate(text, audio_prompt=str(reference))
            torchaudio.save(str(output), wav.cpu(), 24000)
        return output
