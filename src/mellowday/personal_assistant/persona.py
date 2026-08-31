"""The single locally persisted Persona managed by the User."""

from dataclasses import dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True, slots=True)
class Persona:
    name: str
    identity: str
    character: str
    speaking_style: str
    relationship_framing: str
    conversational_boundaries: str
    proactive_chat_style: str

    def chat_instructions(self) -> str:
        """Render Persona guidance exclusively for model-produced Chat Content."""

        return "\n".join(
            (
                "Use this User-managed Persona for all Chat Content, including "
                "normal replies, conversational failures, clarifications, and refusals.",
                f"Assistant name: {self.name}",
                f"Identity: {self.identity}",
                f"Character: {self.character}",
                f"Speaking style: {self.speaking_style}",
                f"Relationship framing: {self.relationship_framing}",
                f"Conversational boundaries: {self.conversational_boundaries}",
                f"Proactive-chat style: {self.proactive_chat_style}",
                "Remain truthful about system state and failures. Persona applies only "
                "to Chat Content, never to Settings, records, permissions, logs, runtime "
                "events, audit output, or diagnostics. You cannot change this saved Persona.",
            )
        )

    def provider_failure_chat_content(self, code: str) -> str:
        """Render truthful Chat Content when no model reply is available."""

        details = {
            "not_configured": (
                "no model Provider is selected. Please choose one in Settings"
            ),
            "authentication": (
                "the configured model Provider rejected its credentials. "
                "Please check Provider Settings"
            ),
            "rate_limited": "the configured model Provider is rate-limited",
            "timeout": "the configured model Provider timed out",
            "unavailable": "the configured model Provider is unavailable",
            "request_rejected": "the configured model Provider rejected the request",
            "invalid_response": (
                "the configured model Provider returned an invalid response"
            ),
        }
        detail = details.get(code, "the configured model Provider failed")
        return f"I can't answer reliably right now because {detail}."

    def reminder_chat_content(self, message: str) -> str:
        """Render a truthful Reminder as Persona-owned Chat Content."""

        return f"{self.name} reminder: {message}"


DEFAULT_PERSONA = Persona(
    name="Mellowday",
    identity="a persistent personal companion",
    character="warm, attentive, and truthful",
    speaking_style="natural, calm, and clear",
    relationship_framing="a trusted companion serving one User",
    conversational_boundaries="do not invent facts or obscure system state",
    proactive_chat_style="short, considerate, and low-pressure",
)


class SQLitePersonaStore:
    """Persist exactly one Persona for an installation."""

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def get(self) -> Persona:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT name, identity, character, speaking_style,
                       relationship_framing, conversational_boundaries,
                       proactive_chat_style
                FROM persona
                WHERE installation_id = 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("Persona storage is not initialized")
        return Persona(*row)

    def update(self, persona: Persona) -> Persona:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE persona
                SET name = ?, identity = ?, character = ?, speaking_style = ?,
                    relationship_framing = ?, conversational_boundaries = ?,
                    proactive_chat_style = ?
                WHERE installation_id = 1
                """,
                (
                    persona.name,
                    persona.identity,
                    persona.character,
                    persona.speaking_style,
                    persona.relationship_framing,
                    persona.conversational_boundaries,
                    persona.proactive_chat_style,
                ),
            )
        return persona

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS persona (
                    installation_id INTEGER PRIMARY KEY CHECK (installation_id = 1),
                    name TEXT NOT NULL,
                    identity TEXT NOT NULL,
                    character TEXT NOT NULL,
                    speaking_style TEXT NOT NULL,
                    relationship_framing TEXT NOT NULL,
                    conversational_boundaries TEXT NOT NULL,
                    proactive_chat_style TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO persona (
                    installation_id, name, identity, character, speaking_style,
                    relationship_framing, conversational_boundaries,
                    proactive_chat_style
                ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    DEFAULT_PERSONA.name,
                    DEFAULT_PERSONA.identity,
                    DEFAULT_PERSONA.character,
                    DEFAULT_PERSONA.speaking_style,
                    DEFAULT_PERSONA.relationship_framing,
                    DEFAULT_PERSONA.conversational_boundaries,
                    DEFAULT_PERSONA.proactive_chat_style,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)
