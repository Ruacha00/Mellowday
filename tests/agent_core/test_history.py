import sqlite3
from pathlib import Path

from mellowday.agent_core import ChatContent, SQLiteConversationHistory


def test_idempotent_delivery_migrates_existing_history_and_appends_once(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE conversations (
                conversation_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE conversation_messages (
                message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY (conversation_id)
                    REFERENCES conversations(conversation_id) ON DELETE CASCADE
            );
            CREATE INDEX conversation_messages_by_conversation
                ON conversation_messages(conversation_id, message_id);
            PRAGMA user_version = 1;
            """
        )

    history = SQLiteConversationHistory(database_path, clock=lambda: 42.0)
    message = ChatContent(role="assistant", content="Mellowday reminder: Call")

    assert history.append_once(
        "main", message, deduplication_key="reminder:one"
    ) is True
    assert history.append_once(
        "main", message, deduplication_key="reminder:one"
    ) is False
    assert history.get_conversation("main").messages == (message,)
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
