"""Bounded neutral process logs for the integrated Settings surface."""

from __future__ import annotations

import logging
from collections import deque
from threading import Lock
from typing import cast


_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


class LogRingBuffer(logging.Handler):
    def __init__(self, capacity: int = 2_000) -> None:
        super().__init__(level=logging.NOTSET)
        self._records: deque[dict[str, object]] = deque(
            maxlen=max(1, capacity)
        )
        self._sequence = 0

    @property
    def cursor(self) -> int:
        return self._sequence

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._sequence += 1
            self._records.append(
                {
                    "sequence": self._sequence,
                    "occurred_at": record.created,
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            )
        except Exception:
            self.handleError(record)

    def query(
        self,
        *,
        since: int = 0,
        limit: int = 200,
        minimum_level: str = "",
        contains: str = "",
    ) -> tuple[dict[str, object], ...]:
        minimum_rank = _LEVELS.get(minimum_level.upper(), 0)
        needle = contains.casefold()
        matched = [
            item
            for item in tuple(self._records)
            if cast(int, item["sequence"]) > since
            and _LEVELS.get(str(item["level"]), 0) >= minimum_rank
            and (
                not needle
                or needle in str(item["message"]).casefold()
                or needle in str(item["logger"]).casefold()
            )
        ]
        bounded_limit = max(1, limit)
        selected = matched[:bounded_limit] if since else matched[-bounded_limit:]
        return tuple(selected)


_install_lock = Lock()
_installed_buffer: LogRingBuffer | None = None


def install_log_buffer() -> LogRingBuffer:
    global _installed_buffer
    with _install_lock:
        if _installed_buffer is None:
            _installed_buffer = LogRingBuffer()
            logging.getLogger("mellowday").addHandler(_installed_buffer)
        return _installed_buffer


__all__ = ["LogRingBuffer", "install_log_buffer"]
