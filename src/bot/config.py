from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str

    # Shared secret the ingest client (Tasker) sends in the X-Auth-Token header.
    ingest_token: str

    # Telegram user IDs allowed to query the location. Anyone else is denied.
    allowed_user_ids: list[int] = []

    database_path: str = "./locations.db"

    # Railway injects PORT; the aiohttp ingest server binds to it.
    port: int = 8080

    log_level: str = "INFO"

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def parse_allowed_user_ids(cls, v: object) -> list[int]:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(x.strip()) for x in v.split(",")]
        if isinstance(v, list):
            return [int(x) for x in v]
        return []

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
