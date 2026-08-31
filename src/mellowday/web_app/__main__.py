"""Development entry point for the complete local Web App."""

import os

import uvicorn

from .app import create_app


def main() -> None:
    installation_timezone = os.environ.get(
        "MELLOWDAY_TIMEZONE", os.environ.get("TZ", "UTC")
    )
    uvicorn.run(
        create_app(installation_timezone=installation_timezone),
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()
