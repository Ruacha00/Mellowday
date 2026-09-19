"""Discovery must follow the current data root without leaking a prior library."""
from pathlib import Path

import pytest

from mellowday.runtime.skills import discover_skills, get_skill_by_name, reset_skill_cache


@pytest.fixture(autouse=True)
def clear_cache():
    reset_skill_cache()
    yield
    reset_skill_cache()


def write_skill(root: Path, text: str):
    directory = root / "skills" / "planning"
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: planning\ndescription: Planning\n---\n" + text, encoding="utf-8")


def test_switching_to_empty_data_root_does_not_reuse_prior_skills(tmp_path, monkeypatch):
    first, empty = tmp_path / "first", tmp_path / "empty"
    write_skill(first, "First library")
    monkeypatch.setenv("MELLOWDAY_DATA_DIR", str(first))
    assert [skill.name for skill in discover_skills()] == ["planning"]
    monkeypatch.setenv("MELLOWDAY_DATA_DIR", str(empty))
    assert discover_skills() == []
    assert get_skill_by_name("planning") is None
    monkeypatch.setenv("MELLOWDAY_DATA_DIR", str(first))
    assert get_skill_by_name("planning").prompt_template == "First library"


def test_same_named_skill_uses_body_from_each_root_and_reset_still_refreshes(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    write_skill(first, "First rule")
    write_skill(second, "Second rule")
    monkeypatch.setenv("MELLOWDAY_DATA_DIR", str(first))
    assert get_skill_by_name("planning").prompt_template == "First rule"
    monkeypatch.setenv("MELLOWDAY_DATA_DIR", str(second))
    assert get_skill_by_name("planning").prompt_template == "Second rule"
    target = second / "skills" / "planning" / "SKILL.md"
    target.write_text(target.read_text(encoding="utf-8").replace("Second rule", "Updated rule"), encoding="utf-8")
    reset_skill_cache()
    assert get_skill_by_name("planning").prompt_template == "Updated rule"
    monkeypatch.setenv("MELLOWDAY_DATA_DIR", str(first))
    assert get_skill_by_name("planning").prompt_template == "First rule"
