"""Static checks that the chat stream renders every learning event.

The runtime refuses to drop a habit write silently (I24b); that guarantee is
worth nothing if the frontend ignores the events. These assertions are static
because the browser path is exercised by the manual checklist, and they were
mutation-checked: removing any event case or reason string fails the suite.
"""
from __future__ import annotations

from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[2] / "src" / "mellowday" / "web_app" / "static" / "app.js"

LEARNING_EVENTS = (
    "skill_candidate_proposed",
    "skill_candidate_applied",
    "skill_write_denied",
    "skill_candidate_failed",
    "skill_candidate_skipped",
)

REASONS = (
    "user_denied",
    "no_confirmer",
    "permission_mode",
    "disabled",
    "plan_mode",
    "no_window",
    "no_model_client",
    "skills_unavailable",
)


@pytest.fixture(scope="module")
def source() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.mark.parametrize("event_type", LEARNING_EVENTS)
def test_every_learning_event_has_a_case(source: str, event_type: str) -> None:
    assert f'case "{event_type}"' in source, f"{event_type} would be swallowed by default:"


@pytest.mark.parametrize("reason", REASONS)
def test_every_denial_reason_is_explained(source: str, reason: str) -> None:
    # Anchored to the start of the key inside the map: a plain "reason:" search
    # is satisfied by a renamed key such as xno_confirmer:, which would leave the
    # real reason unmapped while the test still passed.
    marker = f'\n  {reason}: "'
    assert marker in source, f"{reason} has no user-facing explanation"


def test_unknown_reason_falls_back_to_something_visible(source: str) -> None:
    assert "原因未知" in source


def test_confirm_error_prefix_is_handled(source: str) -> None:
    assert "confirm_error:" in source


def test_applied_event_refreshes_the_habit_list(source: str) -> None:
    assert "state.view === \"skills\"" in source
