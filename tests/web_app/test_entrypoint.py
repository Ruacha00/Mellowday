from fastapi import FastAPI

from mellowday.web_app import __main__ as entrypoint


def test_entrypoint_uses_the_configured_installation_timezone(
    monkeypatch,
) -> None:
    app = FastAPI()
    received: dict[str, object] = {}

    def fake_create_app(*, installation_timezone: str) -> FastAPI:
        received["installation_timezone"] = installation_timezone
        return app

    def fake_run(candidate: FastAPI, *, host: str, port: int) -> None:
        received.update(app=candidate, host=host, port=port)

    monkeypatch.setenv("MELLOWDAY_TIMEZONE", "Asia/Shanghai")
    monkeypatch.setattr(entrypoint, "create_app", fake_create_app)
    monkeypatch.setattr(
        entrypoint.uvicorn,
        "run",
        fake_run,
    )

    entrypoint.main()

    assert received == {
        "installation_timezone": "Asia/Shanghai",
        "app": app,
        "host": "127.0.0.1",
        "port": 8000,
    }
