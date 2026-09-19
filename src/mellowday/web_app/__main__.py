"""Entry point for `python -m mellowday.web_app`."""
from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="mellowday.web_app", description="Run the MellowDay web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--data-dir", default="")
    args = parser.parse_args()

    if args.data_dir:
        Path(args.data_dir).mkdir(parents=True, exist_ok=True)
        import os

        os.environ["MELLOWDAY_DATA_DIR"] = args.data_dir

    uvicorn.run(
        "mellowday.web_app.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
