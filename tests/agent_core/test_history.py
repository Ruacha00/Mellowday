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
            INSERT INTO conversations(conversation_id, created_at, updated_at)
                VALUES ('legacy', 1, 1);
            INSERT INTO conversation_messages(
                conversation_id, role, content, created_at
            ) VALUES ('legacy', 'user', 'Existing message', 1);
            PRAGMA user_version = 1;
            """
        )

    history = SQLiteConversationHistory(database_path, clock=lambda: 42.0)
    message = ChatContent(role="assistant", content="Mellowday reminder: Call")

    assert history.append_once(
        "main", message, deduplication_key="reminder:one", source="reminder"
    ) is True
    assert history.append_once(
        "main", message, deduplication_key="reminder:one", source="reminder"
    ) is False
    stored = history.get_conversation("main")

    assert stored is not None
    assert stored.messages[0].role == message.role
    assert stored.messages[0].content == message.content
    assert stored.messages[0].source == "reminder"
    legacy = history.get_conversation("legacy")
    assert legacy is not None
    assert legacy.messages[0].content == "Existing message"
    assert legacy.summary.title is None
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
    assert stored.summary.title is None


def test_conversation_summary_exposes_first_stored_content_for_title_fallback(
    tmp_path: Path,
) -> None:
    history = SQLiteConversationHistory(
        tmp_path / "mellowday.sqlite3", clock=lambda: 42.0
    )
    history.append(
        "main",
        (
            ChatContent(role="user", content="  Plan   the launch\nnext week  "),
            ChatContent(role="assistant", content="Let's make a checklist."),
        ),
    )

    summary = history.list_conversations()[0]

    assert summary.preview == "  Plan   the launch\nnext week  "


def test_conversation_title_migrates_and_persists_without_reordering_activity(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    history = SQLiteConversationHistory(database_path, clock=lambda: 42.0)
    history.append("main", (ChatContent(role="user", content="Plan the week"),))

    renamed = history.rename("main", "周计划")

    assert renamed is not None
    assert renamed.title == "周计划"
    assert renamed.updated_at == 42.0
    restarted = SQLiteConversationHistory(database_path, clock=lambda: 99.0)
    assert restarted.get_conversation("main").summary.title == "周计划"  # type: ignore[union-attr]
    assert restarted.rename("missing", "不存在") is None
