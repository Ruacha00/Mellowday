"""Registered Tool adapter for the derived Daily Review."""

from mellowday.agent_core import Tool

from .daily_review import DailyReviewService, daily_review_payload


def build_daily_review_tools(service: DailyReviewService) -> tuple[Tool, ...]:
    async def get_review(
        _arguments: dict[str, object], _conversation_id: str
    ) -> object:
        return {"daily_review": daily_review_payload(service.get())}

    return (
        Tool(
            name="daily_review_get",
            description=(
                "Read today's Daily Review derived from the User's current Tasks, "
                "Reminders, Calendar Events, and relevant Notes."
            ),
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            executor=get_review,
            permission_requirements=("daily_review:read",),
            side_effect="none",
        ),
    )


__all__ = ["build_daily_review_tools"]
