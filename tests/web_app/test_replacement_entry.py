import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import FakeProvider
from mellowday.web_app import create_app


def test_production_root_serves_react_and_replacement_redirects(
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
            production = await client.get("/")
            replacement = await client.get("/replacement", follow_redirects=False)
            legacy_javascript = await client.get("/static/app.js")
            legacy_styles = await client.get("/static/styles.css")

        assert production.status_code == 200
        assert '<div id="root"></div>' in production.text
        assert '/static/replacement/assets/' in production.text
        assert replacement.status_code == 308
        assert replacement.headers["location"] == "/"
        assert legacy_javascript.status_code == 404
        assert legacy_styles.status_code == 404

    asyncio.run(exercise_boundary())
