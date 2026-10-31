import json
import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
COLLECT = ROOT / "scripts" / "collect_mac_usage.py"
GROUND = ROOT / "scripts" / "source_grounding.py"
WEBKIT_2026 = (1_773_300_000 + 11_644_473_600) * 1_000_000
MAC_2026 = 1_773_300_000 - 978_307_200

pytestmark = pytest.mark.skipif(sys.platform != "darwin" or os.geteuid() == 0, reason="macOS, non-root only")


def make_db(path: Path, ddl: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    for s in ddl:
        con.execute(s)
    con.commit()
    con.close()


@pytest.fixture
def home(tmp_path: Path) -> Iterator[Path]:
    h = tmp_path / "home"
    make_db(h / "Library/Application Support/Google/Chrome/Default/History", [
        "CREATE TABLE urls(id INTEGER PRIMARY KEY, url TEXT, title TEXT)",
        "CREATE TABLE visits(id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)",
        "INSERT INTO urls VALUES(1, 'https://example.com/', '예시')",
        f"INSERT INTO visits VALUES(1, 1, {WEBKIT_2026})",
        f"INSERT INTO visits VALUES(2, 1, {WEBKIT_2026 + 60_000_000})",
    ])
    make_db(h / "Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2", [
        "CREATE TABLE LSQuarantineEvent(LSQuarantineTimeStamp REAL, LSQuarantineAgentName TEXT, LSQuarantineDataURLString TEXT, LSQuarantineOriginURLString TEXT)",
        f"INSERT INTO LSQuarantineEvent VALUES({MAC_2026}, 'Chrome', 'https://example.com/a.zip', '')",
    ])
    safari = h / "Library/Safari/History.db"
    make_db(safari, ["CREATE TABLE history_items(id INTEGER PRIMARY KEY, url TEXT)"])
    safari.chmod(0)
    yield h
    safari.chmod(0o600)


def collect(home: Path, out: Path, *extra: str) -> dict[str, Any]:
    proc = subprocess.run([sys.executable, str(COLLECT), "--home", str(home), "--out", str(out), *extra],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return {s["id"]: s for s in json.loads((out / "coverage.json").read_text(encoding="utf-8"))["sources"]}


def test_statuses_and_time_conversion(home: Path, tmp_path: Path):
    cov = collect(home, tmp_path / "evidence")
    assert cov["chromium_history"]["status"] == "OK" and cov["chromium_history"]["rows"] == 2
    assert cov["downloads"]["rows"] == 1
    assert cov["safari_history"]["status"] == "DENIED"
    assert cov["firefox_history"]["status"] == "ABSENT"
    assert cov["unified_log"]["status"] == "SKIPPED"
    first = (tmp_path / "evidence" / "chromium_history.txt").read_text(encoding="utf-8").splitlines()[1]
    assert first.startswith("2026-03-12 ") and "https://example.com/" in first


def test_unreadable_folder_is_denied_not_absent(home: Path, tmp_path: Path):
    chrome = home / "Library/Application Support/Google/Chrome"
    chrome.chmod(0)
    try:
        cov = collect(home, tmp_path / "evidence")
    finally:
        chrome.chmod(0o700)
    assert cov["chromium_history"]["status"] == "DENIED", cov["chromium_history"]


def test_window_filters_rows(home: Path, tmp_path: Path):
    cov = collect(home, tmp_path / "evidence", "--since", "2026-04-01")
    assert cov["chromium_history"]["status"] == "OK" and cov["chromium_history"]["rows"] == 0


@pytest.mark.parametrize("line,needle", [
    ("Safari 방문 기록은 없다.", "부재 단정"),
    ("이 기간 사파리 사용 흔적은 없음.", "부재 단정"),
    ("맥북의 모든 사용기록을 검토했다.", "전체 검토 주장"),
])
def test_report_cannot_claim_absence_of_uncollected_source(home: Path, tmp_path: Path, line: str, needle: str):
    collect(home, tmp_path / "evidence")
    rep = tmp_path / "report.md"
    rep.write_text(f"# 보고서\n{line}\n", encoding="utf-8")
    res = json.loads(subprocess.run([sys.executable, str(GROUND), str(rep), "--sources", str(tmp_path / "evidence"), "--json"],
                                    capture_output=True, text=True, encoding="utf-8").stdout)
    assert any(needle in e for e in res["errors"]), res["errors"]


def test_honest_report_passes(home: Path, tmp_path: Path):
    collect(home, tmp_path / "evidence")
    rep = tmp_path / "report.md"
    rep.write_text("# 보고서\nSafari 방문 기록: 미확인(권한 없음).\nChrome 방문 기록 2건, Firefox 기록은 없다.\n", encoding="utf-8")
    res = json.loads(subprocess.run([sys.executable, str(GROUND), str(rep), "--sources", str(tmp_path / "evidence"), "--json"],
                                    capture_output=True, text=True, encoding="utf-8").stdout)
    assert res["verdict"] == "PASS", res["errors"]
