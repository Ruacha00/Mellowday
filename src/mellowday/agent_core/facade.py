"""The public orchestration facade for one conversation turn."""

import time
from collections.abc import Callable

from .provider import ModelProvider
from .types import ChatContent, RuntimeEvent, TurnRequest, TurnResult


class AgentCore:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._provider = provider
        self._clock = clock

    async def run_turn(self, request: TurnRequest) -> TurnResult:
        conversation_id = request.conversation_id.strip()
        messages = tuple(
            ChatContent(role=message.role, content=message.content.strip())
            for message in request.messages
        )
        events: list[RuntimeEvent] = []

        def emit(event_type: str, **details: object) -> None:
            events.append(
                RuntimeEvent(
                    sequence=len(events) + 1,
                    type=event_type,
                    occurred_at=self._clock(),
                    conversation_id=conversation_id,
                    details=details,
                )
            )

        emit("turn_started", message_count=len(messages))
        emit("provider_started", provider=self._provider.name)
        reply = await self._provider.complete(messages)
        emit("provider_completed", provider=self._provider.name)

        chat_content = ChatContent(role="assistant", content=reply.content.strip())
        emit("turn_completed", stop_reason="final")
        return TurnResult(
            chat_content=chat_content,
            stop_reason="final",
            events=tuple(events),
        )

