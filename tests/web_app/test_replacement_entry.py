import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import FakeProvider
from mellowday.web_app import create_app


def test_react_replacement_opens_without_replacing_legacy_entry(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            legacy = await client.get("/")
            replacement = await client.get("/replacement")

        assert legacy.status_code == 200
        assert '/static/app.js' in legacy.text
        assert replacement.status_code == 200
        assert '<div id="root"></div>' in replacement.text
        assert '/static/replacement/assets/' in replacement.text

    asyncio.run(exercise_boundary())
