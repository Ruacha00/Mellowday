"""Local persistence for model Provider configurations shown in Settings."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from mellowday.agent_core import FakeProvider, ProviderReply, ProviderRequest
from mellowday.agent_core.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderTransport,
)


@dataclass(frozen=True, slots=True)
class ProviderConfiguration:
    id: str
    name: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    max_retries: int
    enabled: bool
    selected: bool

    def settings_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["api_key"] = mask_credential(self.api_key)
        return payload


def mask_credential(value: str) -> str:
    if not value:
        return ""
    return f"••••{value[-4:]}"


class SQLiteProviderConfigurationStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def create(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> ProviderConfiguration:
        provider = ProviderConfiguration(
            id=str(uuid4()),
            name=name.strip(),
            base_url=base_url.rstrip("/"),
            model=model.strip(),
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            enabled=True,
            selected=False,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO model_providers (
                    id, name, base_url, model, api_key, timeout_seconds,
                    max_retries, enabled, selected
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider.id,
                    provider.name,
                    provider.base_url,
                    provider.model,
                    provider.api_key,
                    provider.timeout_seconds,
                    provider.max_retries,
                    provider.enabled,
                    provider.selected,
                ),
            )
        return provider

    def list(self) -> tuple[ProviderConfiguration, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, name, base_url, model, api_key, timeout_seconds,
                       max_retries, enabled, selected
                FROM model_providers ORDER BY rowid
                """
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def get(self, provider_id: str) -> ProviderConfiguration | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, base_url, model, api_key, timeout_seconds,
                       max_retries, enabled, selected
                FROM model_providers WHERE id = ?
                """,
                (provider_id,),
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def selected(self) -> ProviderConfiguration | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, name, base_url, model, api_key, timeout_seconds,
                       max_retries, enabled, selected
                FROM model_providers WHERE selected = 1 AND enabled = 1 LIMIT 1
                """
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def update(
        self,
        provider_id: str,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float,
        max_retries: int,
    ) -> ProviderConfiguration | None:
        current = self.get(provider_id)
        if current is None:
            return None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE model_providers
                SET name = ?, base_url = ?, model = ?, api_key = ?,
                    timeout_seconds = ?, max_retries = ?
                WHERE id = ?
                """,
                (
                    name.strip(),
                    base_url.rstrip("/"),
                    model.strip(),
                    api_key or current.api_key,
                    timeout_seconds,
                    max_retries,
                    provider_id,
                ),
            )
        return self.get(provider_id)

    def select(self, provider_id: str) -> ProviderConfiguration | None:
        current = self.get(provider_id)
        if current is None or not current.enabled:
            return None
        with self._connect() as connection:
            connection.execute("UPDATE model_providers SET selected = 0")
            connection.execute(
                "UPDATE model_providers SET selected = 1 WHERE id = ?",
                (provider_id,),
            )
        return self.get(provider_id)

    def set_enabled(
        self, provider_id: str, enabled: bool
    ) -> ProviderConfiguration | None:
        if self.get(provider_id) is None:
            return None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE model_providers
                SET enabled = ?, selected = CASE WHEN ? = 0 THEN 0 ELSE selected END
                WHERE id = ?
                """,
                (enabled, enabled, provider_id),
            )
        return self.get(provider_id)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS model_providers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    model TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    timeout_seconds REAL NOT NULL,
                    max_retries INTEGER NOT NULL,
                    enabled INTEGER NOT NULL,
                    selected INTEGER NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ProviderConfiguration:
        return ProviderConfiguration(
            id=str(row["id"]),
            name=str(row["name"]),
            base_url=str(row["base_url"]),
            model=str(row["model"]),
            api_key=str(row["api_key"]),
            timeout_seconds=float(row["timeout_seconds"]),
            max_retries=int(row["max_retries"]),
            enabled=bool(row["enabled"]),
            selected=bool(row["selected"]),
        )


class SelectedProvider:
    """Resolve the selected local Provider configuration for every turn."""

    def __init__(
        self,
        store: SQLiteProviderConfigurationStore,
        transport: ProviderTransport,
    ) -> None:
        self._store = store
        self._transport = transport
        self._fallback = FakeProvider()

    @property
    def name(self) -> str:
        selected = self._store.selected()
        return selected.name if selected is not None else self._fallback.name

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        selected = self._store.selected()
        if selected is None:
            return await self._fallback.complete(request)
        provider = build_openai_compatible_provider(selected, self._transport)
        return await provider.complete(request)


def build_openai_compatible_provider(
    configuration: ProviderConfiguration,
    transport: ProviderTransport,
) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            name=configuration.name,
            base_url=configuration.base_url,
            model=configuration.model,
            api_key=configuration.api_key,
            timeout_seconds=configuration.timeout_seconds,
            max_retries=configuration.max_retries,
        ),
        transport=transport,
    )


__all__ = [
    "ProviderConfiguration",
    "SelectedProvider",
    "SQLiteProviderConfigurationStore",
    "build_openai_compatible_provider",
    "mask_credential",
]
