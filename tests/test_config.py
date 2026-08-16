from src.bot.config import Settings


def test_parse_allowed_user_ids_from_string() -> None:
    settings = Settings(
        telegram_bot_token="tok",
        ingest_token="secret",
        allowed_user_ids="123, 456",  # type: ignore[arg-type]
    )
    assert settings.allowed_user_ids == [123, 456]


def test_parse_allowed_user_ids_from_int() -> None:
    settings = Settings(
        telegram_bot_token="tok",
        ingest_token="secret",
        allowed_user_ids=123,  # type: ignore[arg-type]
    )
    assert settings.allowed_user_ids == [123]


def test_parse_empty_allowed_user_ids() -> None:
    settings = Settings(
        telegram_bot_token="tok",
        ingest_token="secret",
        allowed_user_ids="",  # type: ignore[arg-type]
    )
    assert settings.allowed_user_ids == []


def test_defaults() -> None:
    settings = Settings(telegram_bot_token="tok", ingest_token="secret")
    assert settings.database_path == "./locations.db"
    assert settings.port == 8080
    assert settings.log_level == "INFO"
