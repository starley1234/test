from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./specgraph.db"
    sqlite_fallback: bool = True
    tika_server_url: str = "http://localhost:9998"
    upload_dir: Path = Path("./data/uploads")
    media_dir: Path = Path("./data/media")
    embedding_dim: int = 384
    max_reqs_per_run: int = 40
    max_parallel_jobs: int = 3
    guest_pipelines: bool = True
    guest_max_reqs: int = 8

    admin_username: str = "admin"
    admin_password: str = "admin"
    admin_email: str = "admin@local"

    cheap_base_url: str = "https://api.openai.com/v1"
    cheap_api_key: str = ""
    cheap_model: str = "gpt-4o-mini"

    expensive_base_url: str = "https://api.openai.com/v1"
    expensive_api_key: str = ""
    expensive_model: str = "gpt-4o"

    embed_base_url: str = ""
    embed_api_key: str = ""
    embed_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    # 4. VLM — разбор принципиальных схем (картинка / страница PDF)
    vlm_base_url: str = ""
    vlm_api_key: str = ""
    vlm_model: str = "gpt-4o"

    openai_api_key: str = ""
    openai_model: str = ""
    embedding_model: str = ""

    def cheap(self) -> tuple[str, str, str]:
        key = self.cheap_api_key or self.openai_api_key
        model = self.cheap_model or self.openai_model or "gpt-4o-mini"
        return self.cheap_base_url, key, model

    def expensive(self) -> tuple[str, str, str]:
        key = self.expensive_api_key or self.cheap_api_key or self.openai_api_key
        model = self.expensive_model or "gpt-4o"
        return self.expensive_base_url, key, model

    def embed(self) -> tuple[str, str, str]:
        model = self.embed_model or self.embedding_model or "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        return self.embed_base_url, self.embed_api_key, model

    def vlm(self) -> tuple[str, str, str]:
        e_base, e_key, e_model = self.expensive()
        base = self.vlm_base_url or e_base
        key = self.vlm_api_key or e_key
        model = self.vlm_model or e_model or "gpt-4o"
        return base, key, model


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.media_dir.mkdir(parents=True, exist_ok=True)
