import asyncio
import json
import sqlite3
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from mellowday.web_app.runtime import (
    BackupError,
    RuntimeConfiguration,
    RuntimeConfigurationError,
    backup_installation,
    create_production_app,
    migrate_installation,
)


def test_environment_controls_all_production_paths_and_network_binding(
    tmp_path: Path,
) -> None:
    configuration = RuntimeConfiguration.from_environment(
        {
            "MELLOWDAY_DATA_DIR": str(tmp_path / "user-data"),
            "MELLOWDAY_HOST": "localhost",
            "MELLOWDAY_PORT": "8123",
            "MELLOWDAY_TIMEZONE": "Asia/Shanghai",
        }
    )

    assert configuration.data_directory == (tmp_path / "user-data").resolve()
    assert configuration.database_path.parent == configuration.data_directory
    assert configuration.skill_state_path.parent == configuration.data_directory
    assert configuration.audit_path.parent == configuration.data_directory
    assert configuration.host == "localhost"
    assert configuration.port == 8123
    assert configuration.installation_timezone == "Asia/Shanghai"


def test_non_loopback_binding_requires_explicit_opt_in(tmp_path: Path) -> None:
    environment = {
        "MELLOWDAY_DATA_DIR": str(tmp_path),
        "MELLOWDAY_HOST": "0.0.0.0",
    }
    with pytest.raises(RuntimeConfigurationError, match="ALLOW_REMOTE"):
        RuntimeConfiguration.from_environment(environment)

    environment["MELLOWDAY_ALLOW_REMOTE"] = "1"
    assert RuntimeConfiguration.from_environment(environment).host == "0.0.0.0"


def test_production_app_serves_every_surface_without_live_model_access(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        configuration = RuntimeConfiguration(
            data_directory=tmp_path / "installation"
        )
        app = create_production_app(configuration)
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                conversation = await client.get("/")
                settings = await client.get("/api/settings/status")
                health = await client.get("/healthz")
                chat = await client.post(
                    "/api/chat",
                    json={"conversation_id": "main", "content": "Hello"},
                )
                proactive = await client.get("/api/settings/proactive-chat")

        assert conversation.status_code == 200
        assert "Mellowday" in conversation.text
        assert settings.json()["backend"] == {
            "ok": True,
            "service": "mellowday",
        }
        assert settings.json()["provider"]["configured"] is False
        assert health.json() == {"ok": True}
        assert chat.json()["stop_reason"] == "provider_error"
        assert proactive.status_code == 200
        assert configuration.database_path.is_file()

    asyncio.run(exercise())


def test_migrate_and_consistent_backup_cover_all_local_state(tmp_path: Path) -> None:
    configuration = RuntimeConfiguration(data_directory=tmp_path / "installation")
    database_path = migrate_installation(configuration)
    configuration.skill_state_path.write_text(
        json.dumps({"concise": False}), encoding="utf-8"
    )
    configuration.audit_path.write_text("audit\n", encoding="utf-8")

    with sqlite3.connect(database_path) as connection:
        table_names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "conversations",
        "model_providers",
        "persona",
        "memories",
        "tasks",
        "reminders",
        "calendar_events",
        "notes",
        "proactive_chat_settings",
    } <= table_names

    backup_path = backup_installation(configuration, tmp_path / "backup")
    assert (backup_path / "mellowday.sqlite3").is_file()
    assert (backup_path / "skill-enablement.json").read_text(
        encoding="utf-8"
    ) == json.dumps({"concise": False})
    assert (backup_path / "audit-events.jsonl").read_text(
        encoding="utf-8"
    ) == "audit\n"
    with sqlite3.connect(backup_path / "mellowday.sqlite3") as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2

    with pytest.raises(BackupError, match="already exists"):
        backup_installation(configuration, backup_path)
    with pytest.raises(BackupError, match="outside"):
        backup_installation(configuration, configuration.data_directory / "backup")
