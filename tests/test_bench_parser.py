"""bench_parser.py 스모크 — 지표가 산출되고 표 재현도가 1.0인지 확인."""
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import bench_parser as bp  # noqa: E402


def test_benchmark_reports_metrics():
    result = bp.run_benchmark(docs=2, pages=5)
    assert result["pages_total"] == 10
    assert result["pages_per_sec"] and result["pages_per_sec"] > 0
    assert result["table_fidelity"] == 1.0
    assert result["cells_extracted"] == result["cells_expected"]


def test_benchmark_json_cli(capsys):
    assert bp.main(["--docs", "1", "--pages", "3", "--json"]) == 0
    import json
    out = json.loads(capsys.readouterr().out)
    assert out["docs"] == 1 and out["table_fidelity"] == 1.0
