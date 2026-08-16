from src.bot.config import Settings

REQUIRED = {
    "telegram_bot_token": "tok",
    "ingest_token": "secret",
    "access_password": "pw",
}


def test_parse_user_id_lists_from_string() -> None:
    settings = Settings(
        **REQUIRED,
        admin_user_ids="123, 456",  # type: ignore[arg-type]
        allowed_user_ids="789",  # type: ignore[arg-type]
    )
    assert settings.admin_user_ids == [123, 456]
    assert settings.allowed_user_ids == [789]


def test_parse_user_ids_from_int() -> None:
    settings = Settings(**REQUIRED, admin_user_ids=123)  # type: ignore[arg-type]
    assert settings.admin_user_ids == [123]


def test_parse_empty_user_ids() -> None:
    settings = Settings(**REQUIRED, admin_user_ids="")  # type: ignore[arg-type]
    assert settings.admin_user_ids == []


def test_defaults() -> None:
    settings = Settings(**REQUIRED)
    assert settings.database_path == "./locations.db"
    assert settings.port == 8080
    assert settings.retention_days == 7
    assert settings.max_accuracy_m == 500.0
    assert settings.history_hours == 6
    assert settings.history_points == 10
    assert settings.admin_user_ids == []
    assert settings.log_level == "INFO"
