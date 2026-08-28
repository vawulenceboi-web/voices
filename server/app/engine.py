from collections import OrderedDict
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

class ChatterboxEngine:
    """Lazy, single-process boundary around Chatterbox."""
    def __init__(self, device: str, conditioning_cache_size: int = 8):
        self.device = device
        self._model = None
        self._torchaudio = None
        self._lock = Lock()
        self._conditioning_cache_size = max(0, conditioning_cache_size)
        self._conditioning_cache: OrderedDict[str, Any] = OrderedDict()

    def _elapsed_ms(self, started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 2)

    def _sync_if_cuda(self):
        if not self.device.startswith("cuda"):
            return
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.synchronize()
        except Exception:
            return

    def _load(self, timings: dict[str, Any]):
        was_warm = self._model is not None
        started_at = perf_counter()
        if self._model is None:
            from chatterbox.tts import ChatterboxTTS
            self._model = ChatterboxTTS.from_pretrained(device=self.device)
            self._sync_if_cuda()
        timings["model_was_warm"] = was_warm
        timings["model_load_ms"] = self._elapsed_ms(started_at) if not was_warm else 0.0
        return self._model

    def _load_audio_io(self, timings: dict[str, Any]):
        was_warm = self._torchaudio is not None
        started_at = perf_counter()
        if self._torchaudio is None:
            import torchaudio
            self._torchaudio = torchaudio
        timings["audio_io_was_warm"] = was_warm
        timings["audio_io_import_ms"] = self._elapsed_ms(started_at) if not was_warm else 0.0
        return self._torchaudio

    def _cache_key(self, reference: Path, cache_key: str | None) -> str:
        stat = reference.stat()
        key = cache_key or reference.stem
        return f"{key}:{stat.st_size}:{stat.st_mtime_ns}"

    def _get_cached_conditionals(self, key: str):
        if self._conditioning_cache_size == 0:
            return None
        conds = self._conditioning_cache.get(key)
        if conds is not None:
            self._conditioning_cache.move_to_end(key)
        return conds

    def _put_cached_conditionals(self, key: str, conds):
        if self._conditioning_cache_size == 0:
            return
        self._conditioning_cache[key] = conds
        self._conditioning_cache.move_to_end(key)
        while len(self._conditioning_cache) > self._conditioning_cache_size:
            self._conditioning_cache.popitem(last=False)

    def status(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "model_loaded": self._model is not None,
            "audio_io_loaded": self._torchaudio is not None,
            "conditioning_cache": {
                "size": len(self._conditioning_cache),
                "max_size": self._conditioning_cache_size,
            },
        }

    def evict_voice(self, voice_id: str) -> int:
        prefix = f"{voice_id}:"
        with self._lock:
            keys = [key for key in self._conditioning_cache if key == voice_id or key.startswith(prefix)]
            for key in keys:
                del self._conditioning_cache[key]
            return len(keys)

    def warmup(self) -> dict[str, Any]:
        timings: dict[str, Any] = {}
        total_started_at = perf_counter()
        lock_started_at = perf_counter()
        with self._lock:
            timings["lock_wait_ms"] = self._elapsed_ms(lock_started_at)
            self._load_audio_io(timings)
            self._load(timings)
            timings["warmup_total_ms"] = self._elapsed_ms(total_started_at)
        return timings

    def synthesize(self, text: str, reference: Path, output: Path, cache_key: str | None = None) -> dict[str, Any]:
        timings: dict[str, Any] = {}
        total_started_at = perf_counter()
        lock_started_at = perf_counter()
        with self._lock:
            timings["lock_wait_ms"] = self._elapsed_ms(lock_started_at)
            torchaudio = self._load_audio_io(timings)
            model = self._load(timings)

            cache_lookup_started_at = perf_counter()
            conditioning_key = self._cache_key(reference, cache_key)
            conds = self._get_cached_conditionals(conditioning_key)
            timings["reference_cache_lookup_ms"] = self._elapsed_ms(cache_lookup_started_at)
            timings["reference_cache_hit"] = conds is not None

            if conds is None:
                conditioning_started_at = perf_counter()
                model.prepare_conditionals(str(reference))
                self._sync_if_cuda()
                timings["reference_decode_condition_ms"] = self._elapsed_ms(conditioning_started_at)
                self._put_cached_conditionals(conditioning_key, model.conds)
            else:
                model.conds = conds
                timings["reference_decode_condition_ms"] = 0.0

            inference_started_at = perf_counter()
            wav = model.generate(text)
            self._sync_if_cuda()
            timings["gpu_inference_ms"] = self._elapsed_ms(inference_started_at)

            encode_started_at = perf_counter()
            torchaudio.save(str(output), wav.cpu(), getattr(model, "sr", 24000))
            timings["wav_encoding_ms"] = self._elapsed_ms(encode_started_at)
            timings["conditioning_cache_size"] = len(self._conditioning_cache)
            timings["engine_total_ms"] = self._elapsed_ms(total_started_at)
        return timings
