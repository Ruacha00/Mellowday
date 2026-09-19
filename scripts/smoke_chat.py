"""Real-model smoke check for the P1 gate.

Usage:
    python scripts/smoke_chat.py [--session ID] [--out FILE] MESSAGE

Requires MELLOWDAY_API_KEY (put it in .env, or export it). The script streams
the structured event log and can mirror it to a UTF-8 transcript file so results
can be inspected without depending on the console code page.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mellowday import config  # noqa: E402
from mellowday import paths  # noqa: E402
from mellowday.storage.store import Store  # noqa: E402
from mellowday.web_app.service import SessionRegistry  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="MellowDay real-model smoke check")
    parser.add_argument("prompt", nargs="*", help="message to send")
    parser.add_argument("--session", default="smoke")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    cfg = config.load_model_config()
    if not cfg.configured:
        print("MELLOWDAY_API_KEY is not configured; cannot run the real-model gate.")
        return 2
    print("model=" + cfg.model + " base=" + cfg.api_base + " data=" + str(paths.data_dir()))

    message = " ".join(args.prompt) or "你好，请用一句话介绍你能帮我做什么。"
    store = Store()
    registry = SessionRegistry(store=store)

    transcript: list[dict] = []
    failures = 0
    async for event in registry.run_turn(args.session, message):
        transcript.append(event)
        if event.get("type") == "text_delta":
            sys.stdout.write(str(event.get("text") or ""))
            sys.stdout.flush()
        else:
            print("\n[" + str(event.get("type")) + "] " + json.dumps(event, ensure_ascii=False)[:800], flush=True)
        if event.get("type") == "error":
            failures += 1
    print()

    if args.out:
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            for event in transcript:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        print("transcript: " + str(target))

    print("records after turn:")
    for kind in ("todos", "calendar", "reminders", "notes", "memories"):
        rows = store.list_records(kind)
        if rows:
            print("  " + kind + ": " + json.dumps([r["title"] for r in rows], ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
