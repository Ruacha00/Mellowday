"""Artifact paths preserve valid session identifiers and reject unsafe ones."""
import pytest

from mellowday.runtime import sessions


@pytest.mark.parametrize("first,second", [("a", "a-"), ("a", "-a"), ("-", "--")])
def test_artifact_read_and_delete_are_scoped_to_exact_session(first, second):
    original = sessions.save_tool_artifact(first, "notes", "first session")
    other = sessions.save_tool_artifact(second, "notes", "second session")

    assert sessions.read_tool_artifact(second, original["ref"])["error"] == "unknown_ref"
    assert sessions.read_tool_artifact(first, other["ref"])["error"] == "unknown_ref"
    assert sessions.delete_tool_artifacts(second) == 1
    assert sessions.read_tool_artifact(first, original["ref"])["text"] == "first session"


@pytest.mark.parametrize("session_id", ["", "../outside", "a/b", "a\\b", "a" * 65, None])
def test_invalid_session_creates_no_artifact_directory(session_id, isolated_data_dir):
    with pytest.raises(ValueError, match="invalid session id"):
        sessions.save_tool_artifact(session_id, "notes", "payload")
    assert not (isolated_data_dir / sessions.ARTIFACT_DIR_NAME).exists()
