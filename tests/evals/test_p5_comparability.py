"""No model requests: aggregate checks must reject different code snapshots."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def p5(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("p5_comparability_subject", root / "evals/p5_compare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
@pytest.mark.parametrize("fingerprints,expected", [(["same", "same", "same"], 0),
                                                  (["one", "two", "one"], 1),
                                                  ([None, None, None], 1)])
async def test_aggregate_mismatch_is_reported_and_returns_failure(p5, monkeypatch, tmp_path, fingerprints, expected):
    output = tmp_path / "new-report.json"
    monkeypatch.setattr(p5, "parse_args", lambda: SimpleNamespace(
        samples=1, arm_json=None, only=None, isolate_arms=False, json_out=str(output)))

    async def arm(args, condition, samples):
        return {"condition": condition, "fingerprint": fingerprints[list(p5.CONDITIONS).index(condition)],
                "model_config": {"model": "offline-fixture"}, "run": {"run_id": condition},
                "summary": "fixture", "checks": [], "measurements": {
                    case: {"hits": 1, "valid": 1, "of": 1, "samples": []} for case in p5.CASES}}

    monkeypatch.setattr(p5, "run_condition", arm)
    assert await p5.main() == expected
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["cross_arm_comparability"]["passed"] == (expected == 0)
