"""Production configuration and local release operations."""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from .app import create_app


class RuntimeConfigurationError(ValueError):
    """Raised when production environment settings are invalid."""


class BackupError(RuntimeError):
    """Raised when a local installation cannot be backed up safely."""


@dataclass(frozen=True, slots=True)
class RuntimeConfiguration:
    """Resolved production settings for one local installation."""

    data_directory: Path
    host: str = "127.0.0.1"
    port: int = 8000
    installation_timezone: str = "UTC"

    @property
    def database_path(self) -> Path:
        return self.data_directory / "mellowday.sqlite3"

    @property
    def skill_state_path(self) -> Path:
        return self.data_directory / "skill-enablement.json"

    @property
    def audit_path(self) -> Path:
        return self.data_directory / "audit-events.jsonl"

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> RuntimeConfiguration:
        values = os.environ if environment is None else environment
        raw_data_directory = values.get("MELLOWDAY_DATA_DIR", "").strip()
        data_directory = (
            Path(raw_data_directory).expanduser()
            if raw_data_directory
            else _default_data_directory(values)
        )
        host = values.get("MELLOWDAY_HOST", "127.0.0.1").strip()
        if not host:
            raise RuntimeConfigurationError("MELLOWDAY_HOST must not be empty")
        allow_remote = values.get("MELLOWDAY_ALLOW_REMOTE", "").strip() == "1"
        if host not in {"127.0.0.1", "::1", "localhost"} and not allow_remote:
            raise RuntimeConfigurationError(
                "a non-loopback MELLOWDAY_HOST requires MELLOWDAY_ALLOW_REMOTE=1"
            )
        raw_port = values.get("MELLOWDAY_PORT", "8000").strip()
        try:
            port = int(raw_port)
        except ValueError as error:
            raise RuntimeConfigurationError(
                "MELLOWDAY_PORT must be an integer"
            ) from error
        if not 1 <= port <= 65_535:
            raise RuntimeConfigurationError(
                "MELLOWDAY_PORT must be between 1 and 65535"
            )
        timezone = values.get(
            "MELLOWDAY_TIMEZONE", values.get("TZ", "UTC")
        ).strip()
        if not timezone:
            timezone = "UTC"
        return cls(
            data_directory=data_directory.resolve(),
            host=host,
            port=port,
            installation_timezone=timezone,
        )


def create_production_app(configuration: RuntimeConfiguration) -> FastAPI:
    """Create every production surface over one User-controlled data root."""

    configuration.data_directory.mkdir(parents=True, exist_ok=True)
    return create_app(
        conversation_database_path=configuration.database_path,
        skill_state_path=configuration.skill_state_path,
        audit_path=configuration.audit_path,
        installation_timezone=configuration.installation_timezone,
    )


def migrate_installation(configuration: RuntimeConfiguration) -> Path:
    """Apply all idempotent local schema initialization and migrations."""

    create_production_app(configuration)
    return configuration.database_path


def backup_installation(
    configuration: RuntimeConfiguration, destination: str | Path
) -> Path:
    """Create a consistent SQLite snapshot plus the installation's local files."""

    source_directory = configuration.data_directory.resolve()
    destination_directory = Path(destination).expanduser().resolve()
    if not configuration.database_path.is_file():
        raise BackupError(
            "the installation database does not exist; run migrate or start first"
        )
    if destination_directory == source_directory or destination_directory.is_relative_to(
        source_directory
    ):
        raise BackupError("the backup destination must be outside MELLOWDAY_DATA_DIR")
    if destination_directory.exists():
        raise BackupError("the backup destination already exists")

    destination_directory.mkdir(parents=True)
    database_destination = destination_directory / configuration.database_path.name
    with sqlite3.connect(configuration.database_path) as source_connection:
        with sqlite3.connect(database_destination) as target_connection:
            source_connection.backup(target_connection)

    database_sidecars = {
        configuration.database_path.name,
        f"{configuration.database_path.name}-shm",
        f"{configuration.database_path.name}-wal",
    }
    for source_path in source_directory.rglob("*"):
        if not source_path.is_file() or source_path.name in database_sidecars:
            continue
        relative_path = source_path.relative_to(source_directory)
        target_path = destination_directory / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
    return destination_directory


def _default_data_directory(environment: Mapping[str, str]) -> Path:
    if os.name == "nt":
        local_app_data = environment.get("LOCALAPPDATA", "").strip()
        if local_app_data:
            return Path(local_app_data) / "Mellowday"
    xdg_data_home = environment.get("XDG_DATA_HOME", "").strip()
    if xdg_data_home:
        return Path(xdg_data_home) / "mellowday"
    return Path.home() / ".local" / "share" / "mellowday"


__all__ = [
    "BackupError",
    "RuntimeConfiguration",
    "RuntimeConfigurationError",
    "backup_installation",
    "create_production_app",
    "migrate_installation",
]
