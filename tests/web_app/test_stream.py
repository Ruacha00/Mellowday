"""Web layer stream encoding tests (no network, no runtime needed)."""
from __future__ import annotations

import json

import pytest

from mellowday.web_app import stream


def test_sse_frame_is_named_and_parseable():
    frame = stream.to_sse({"type": "text_delta", "text": "你好"})
    assert frame.startswith("event: text_delta\n")
    assert frame.endswith("\n\n")
    payload = json.loads(frame.split("data: ", 1)[1].strip())
    assert payload == {"type": "text_delta", "text": "你好"}


def test_ndjson_frame_has_no_event_name():
    assert stream.to_ndjson({"type": "done"}) == '{"type": "done"}\n'


@pytest.mark.anyio
async def test_channel_delivers_events_in_order_and_stops_on_close():
    channel = stream.EventChannel()
    channel.sink({"type": "one"})
    channel.sink({"type": "two"})
    channel.close()
    channel.sink({"type": "ignored"})

    seen = [event async for event in channel]
    assert [e["type"] for e in seen] == ["one", "two"]


@pytest.mark.anyio
async def test_channel_close_is_idempotent():
    channel = stream.EventChannel()
    channel.close()
    channel.close()
    assert [event async for event in channel] == []
