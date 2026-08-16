from pydantic import field_validator
from pydantic_settings import BaseSettings


def _parse_id_list(v: object) -> list[int]:
    if isinstance(v, int):
        return [v]
    if isinstance(v, str):
        if not v.strip():
            return []
        return [int(x.strip()) for x in v.split(",")]
    if isinstance(v, list):
        return [int(x) for x in v]
    return []


class Settings(BaseSettings):
    telegram_bot_token: str

    # Shared secret the ingest client (Tasker) sends in the X-Auth-Token header.
    ingest_token: str

    # Anyone who sends this password to the bot gets access.
    access_password: str

    # Telegram user IDs with admin rights: they are notified about every
    # location request and can use /block, /unblock and /users.
    admin_user_ids: list[int] = []

    # Users granted access before password login existed, or pre-approved.
    allowed_user_ids: list[int] = []

    database_path: str = "./locations.db"

    # Railway injects PORT; the aiohttp ingest server binds to it.
    port: int = 8080

    # Points older than this are deleted on every ingest.
    retention_days: int = 7

    # Points with a worse reported accuracy (in metres) are rejected — a bad
    # GPS fix would otherwise teleport the track across town.
    max_accuracy_m: float = 500.0

    # How much of the track /where shows.
    history_hours: int = 6
    history_points: int = 10

    log_level: str = "INFO"

    @field_validator("admin_user_ids", "allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, v: object) -> list[int]:
        return _parse_id_list(v)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
