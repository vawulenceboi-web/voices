from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    api_key: str = "change-me"
    database_url: str | None = None
    developer_api_keys_database_url: str | None = None
    developer_api_key_hash_secret: str | None = None
    device: str = "cuda"
    host: str = "0.0.0.0"
    port: int = 8000
    voice_dir: Path = Path("./voices")
    generated_dir: Path = Path("./generated")
    max_reference_mb: int = 25
    max_reference_seconds: int = 30
    max_text_length: int = 3000
    conditioning_cache_size: int = 8
    preload_model: bool = True
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
settings.voice_dir.mkdir(parents=True, exist_ok=True)
settings.generated_dir.mkdir(parents=True, exist_ok=True)
