"""contracts/ 벤더 파일 PIN 해시 일치 — 수동 편집 드리프트 탐지."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_vendored_contracts_match_pin():
    pin = json.loads((ROOT / "contracts" / "PIN.json").read_text())
    for name, want in pin["sha256"].items():
        f = ROOT / "contracts" / name
        assert f.exists(), f"missing vendored file: {name}"
        got = hashlib.sha256(f.read_bytes()).hexdigest()
        assert got == want, f"drift detected in contracts/{name}"
