from pathlib import Path

from fastapi import FastAPI

from mellowday.web_app import __main__ as entrypoint
from mellowday.web_app.runtime import RuntimeConfiguration


def test_entrypoint_uses_resolved_production_configuration(monkeypatch) -> None:
    app = FastAPI()
    configuration = RuntimeConfiguration(
        data_directory=Path("installation-data"),
        host="localhost",
        port=8123,
        installation_timezone="Asia/Shanghai",
    )
    received: dict[str, object] = {}

    monkeypatch.setattr(
        entrypoint.RuntimeConfiguration,
        "from_environment",
        lambda: configuration,
    )

    def fake_create(candidate: RuntimeConfiguration) -> FastAPI:
        received["configuration"] = candidate
        return app

    def fake_run(candidate: FastAPI, *, host: str, port: int) -> None:
        received.update(app=candidate, host=host, port=port)

    monkeypatch.setattr(entrypoint, "create_production_app", fake_create)
    monkeypatch.setattr(entrypoint.uvicorn, "run", fake_run)

    entrypoint.main(("serve",))

    assert received == {
        "configuration": configuration,
        "app": app,
        "host": "localhost",
        "port": 8123,
    }
