#!/usr/bin/env python3
"""collect_mac_usage.py — macOS 사용기록을 읽기 전용으로 수집하고 소스별 수집 상태를 남긴다.

원본 DB는 열지 않고 임시 복사본만 읽는다. 소스마다 OK / DENIED(macOS 권한) / ABSENT / ERROR / SKIPPED 를
coverage.json·coverage.md 에 기록한다. DENIED 가 있으면 --request-access 가 전체 디스크 접근 권한 설정 창을 열고,
--wait-access N 동안 다시 시도한다.

CLI: python collect_mac_usage.py --out evidence [--days 7 | --since 2026-10-01 --until 2026-10-31]
                                 [--request-access] [--wait-access 120] [--unified-log] [--home ~]
"""
from __future__ import annotations

import argparse
import errno
import glob
import json
import os
import plistlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

Row = tuple[Any, ...]
Rec = dict[str, Any]

MAC_EPOCH = 978307200
WEBKIT_EPOCH = 11644473600
FDA_PANE = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"


class Denied(Exception):
    pass


def mac_abs(v: float | None) -> float | None:
    if v is None:
        return None
    v = float(v)
    if v > 1e15:
        v /= 1e9
    return v + MAC_EPOCH


def webkit(v: float | None) -> float | None:
    return None if not v else float(v) / 1e6 - WEBKIT_EPOCH


def is_denied(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EPERM, errno.EACCES):
        return True
    return "authorization denied" in str(exc).lower() or "operation not permitted" in str(exc).lower()


def query(path: Path, sql: str, tmp: Path) -> list[Row]:
    dst = tmp / f"{abs(hash(str(path)))}_{path.name}"
    try:
        shutil.copy2(path, dst)
        for ext in ("-wal", "-shm"):
            side = Path(str(path) + ext)
            if side.exists():
                shutil.copy2(side, Path(str(dst) + ext))
    except OSError as exc:
        if is_denied(exc):
            raise Denied(str(exc)) from exc
        raise
    con = sqlite3.connect(str(dst))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def one_line(*parts: object) -> str:
    return " | ".join(str(p).replace("\n", " ").replace("\r", " ").strip() for p in parts if p not in (None, ""))


def chromium(home: Path, tmp: Path) -> tuple[list[str], list[tuple[float | None, str]]]:
    roots = ["Google/Chrome", "BraveSoftware/Brave-Browser", "Microsoft Edge", "Arc/User Data", "Chromium"]
    paths = [Path(p) for r in roots for p in glob.glob(str(home / "Library/Application Support" / r / "*" / "History"))]
    rows = []
    for p in paths:
        for t, url, title in query(p, "SELECT v.visit_time, u.url, u.title FROM visits v JOIN urls u ON v.url = u.id", tmp):
            rows.append((webkit(t), one_line(p.parent.parent.name, url, title)))
    return [str(p) for p in paths], rows


def firefox(home: Path, tmp: Path):
    paths = [Path(p) for p in glob.glob(str(home / "Library/Application Support/Firefox/Profiles/*/places.sqlite"))]
    rows = []
    for p in paths:
        sql = "SELECT v.visit_date, p.url, p.title FROM moz_historyvisits v JOIN moz_places p ON v.place_id = p.id"
        rows += [(t / 1e6 if t else None, one_line(url, title)) for t, url, title in query(p, sql, tmp)]
    return [str(p) for p in paths], rows


def single_db(rel: str, sql: str, conv: Callable[[Row], tuple[float | None, str]]):
    def run(home: Path, tmp: Path):
        p = home / rel
        if not p.exists():
            return [], None
        return [str(p)], [conv(r) for r in query(p, sql, tmp)]

    return run


def shell_history(home: Path, tmp: Path):
    paths = [p for p in (home / ".zsh_history", home / ".bash_history") if p.exists()]
    rows = []
    for p in paths:
        try:
            raw = p.read_bytes().decode("utf-8", errors="replace")
        except OSError as exc:
            if is_denied(exc):
                raise Denied(str(exc)) from exc
            raise
        for line in raw.splitlines():
            if line.startswith(": ") and ";" in line:
                head, cmd = line.split(";", 1)
                try:
                    rows.append((float(head.split(":")[1]), one_line(p.name, cmd)))
                    continue
                except (IndexError, ValueError):
                    pass
            if line.strip():
                rows.append((None, one_line(p.name, line)))
    return [str(p) for p in paths], rows


def install_history(home: Path, tmp: Path):
    p = Path("/Library/Receipts/InstallHistory.plist")
    if not p.exists():
        return [], None
    try:
        items = plistlib.loads(p.read_bytes())
    except OSError as exc:
        if is_denied(exc):
            raise Denied(str(exc)) from exc
        raise
    return [str(p)], [(i["date"].timestamp() if i.get("date") else None,
                       one_line(i.get("displayName"), i.get("displayVersion"), i.get("processName"))) for i in items]


def power_log(home: Path, tmp: Path):
    out = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True, timeout=120).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[3].lstrip().split(" ", 1)[0] in {"Sleep", "Wake", "DarkWake", "Shutdown", "Restart"}:
            try:
                ts = datetime.strptime(" ".join(parts[:3]), "%Y-%m-%d %H:%M:%S %z").timestamp()
            except ValueError:
                continue
            rows.append((ts, one_line(parts[3].strip()[:200])))
    return ["pmset -g log"], rows


def unified_log(days: int):
    def run(home: Path, tmp: Path):
        cmd = ["log", "show", "--style", "syslog", "--last", f"{days}d", "--predicate",
               'process == "loginwindow" AND (eventMessage CONTAINS[c] "login" OR eventMessage CONTAINS[c] "logout" OR eventMessage CONTAINS[c] "lock")']
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600).stdout
        rows = []
        for line in out.splitlines():
            try:
                ts = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S").timestamp()
            except ValueError:
                continue
            rows.append((ts, one_line(line[19:].strip()[:300])))
        return [" ".join(cmd[:5])], rows

    return run


SOURCES: list[Rec] = [
    {"id": "chromium_history", "label": "Chrome/Edge/Brave/Arc 방문 기록", "match": r"chrome|크롬|edge|엣지|brave|브레이브|arc", "fn": chromium},
    {"id": "safari_history", "label": "Safari 방문 기록", "match": r"safari|사파리",
     "fn": single_db("Library/Safari/History.db",
                     "SELECT v.visit_time, i.url, v.title FROM history_visits v JOIN history_items i ON v.history_item = i.id",
                     lambda r: (mac_abs(r[0]), one_line(r[1], r[2])))},
    {"id": "firefox_history", "label": "Firefox 방문 기록", "match": r"firefox|파이어폭스", "fn": firefox},
    {"id": "app_usage", "label": "앱 사용 기록(knowledgeC)", "match": r"knowledgec|앱\s*사용|화면\s*시간|스크린\s*타임|screen\s*time",
     "fn": single_db("Library/Application Support/Knowledge/knowledgeC.db",
                     "SELECT ZSTARTDATE, ZENDDATE, ZVALUESTRING FROM ZOBJECT WHERE ZSTREAMNAME = '/app/usage'",
                     lambda r: (mac_abs(r[0]), one_line(r[2], f"종료 {fmt(mac_abs(r[1]))}")))},
    {"id": "downloads", "label": "다운로드 출처 기록(Quarantine)", "match": r"다운로드|quarantine|내려받",
     "fn": single_db("Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2",
                     "SELECT LSQuarantineTimeStamp, LSQuarantineAgentName, LSQuarantineDataURLString, LSQuarantineOriginURLString FROM LSQuarantineEvent",
                     lambda r: (mac_abs(r[0]), one_line(r[1], r[2], r[3])))},
    {"id": "messages", "label": "메시지(iMessage/SMS)", "match": r"imessage|아이메시지|메시지\s*앱|문자\s*메시지|sms",
     "fn": single_db("Library/Messages/chat.db",
                     "SELECT m.date, h.id, m.is_from_me, m.text FROM message m LEFT JOIN handle h ON m.handle_id = h.ROWID",
                     lambda r: (mac_abs(r[0]), one_line(r[1], "보냄" if r[2] else "받음", r[3] if r[3] is not None else "(본문 미추출: attributedBody)")))},
    {"id": "shell_history", "label": "터미널 명령 기록", "match": r"터미널|셸|쉘|zsh|bash|명령\s*(기록|이력)", "fn": shell_history},
    {"id": "install_history", "label": "소프트웨어 설치 기록", "match": r"설치\s*(기록|이력)|installhistory", "fn": install_history},
    {"id": "power_log", "label": "잠자기/깨우기 기록(pmset)", "match": r"잠자기|절전|깨우기|깨어|sleep|wake|전원", "fn": power_log},
    {"id": "unified_log", "label": "로그인/잠금 기록(통합 로그)", "match": r"통합\s*로그|unified\s*log|로그인|로그아웃|화면\s*잠금", "fn": None},
]


def fmt(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else "시각 없음"


def host_app() -> str:
    return os.environ.get("__CFBundleIdentifier") or os.environ.get("TERM_PROGRAM") or "이 명령을 실행한 앱"


def collect(src: Rec, home: Path, window: tuple[float | None, float | None]) -> Rec:
    rec = {k: src[k] for k in ("id", "label", "match")} | {"paths": [], "rows": 0, "status": "", "reason": ""}
    if src["fn"] is None:
        rec.update(status="SKIPPED", reason="--unified-log 를 주면 수집한다(오래 걸림)")
        return rec | {"_rows": []}
    with tempfile.TemporaryDirectory() as td:
        try:
            paths, rows = src["fn"](home, Path(td))
        except Denied as exc:
            rec.update(status="DENIED", reason=f"macOS 권한 거부(전체 디스크 접근 권한 필요): {exc}")
            return rec | {"_rows": []}
        except (sqlite3.Error, OSError, subprocess.SubprocessError, KeyError, ValueError) as exc:
            status = "DENIED" if is_denied(exc) else "ERROR"
            rec.update(status=status, reason=f"{type(exc).__name__}: {exc}")
            return rec | {"_rows": []}
    rec["paths"] = paths
    if rows is None or not paths:
        rec.update(status="ABSENT", reason="이 Mac에 해당 파일이 없다")
        return rec | {"_rows": []}
    lo, hi = window
    kept = [(t, d) for t, d in rows if (t is None and lo is None and hi is None) or (t is not None and (lo is None or t >= lo) and (hi is None or t < hi))]
    kept.sort(key=lambda x: x[0] or 0)
    untimed = sum(1 for t, _ in rows if t is None) if (lo is not None or hi is not None) else 0
    reason = "" if kept else "읽었으나 기간 안 기록 0건"
    if untimed:
        reason = (reason + "; " if reason else "") + f"시각 없는 기록 {untimed}줄은 기간을 판단할 수 없어 제외(기간 없이 다시 실행하면 포함)"
    rec.update(status="OK", rows=len(kept), untimed_excluded=untimed, reason=reason)
    return rec | {"_rows": kept}


def write_outputs(out: Path, recs: list[Rec], window_text: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for r in recs:
        if r["status"] == "OK":
            body = [f"# {r['label']} — {', '.join(r['paths'])}"] + [f"{fmt(t)} | {d}" for t, d in r["_rows"]]
            (out / f"{r['id']}.txt").write_text("\n".join(body) + "\n", encoding="utf-8")
    public = [{k: v for k, v in r.items() if k != "_rows"} for r in recs]
    meta = {"collected_at": fmt(time.time()), "window": window_text, "host_app": host_app(), "sources": public}
    (out / "coverage.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# 수집 범위 ({meta['collected_at']} 수집, 기간: {window_text})", "", "| 소스 | 상태 | 건수 | 사유 |", "|---|---|---|---|"]
    lines += [f"| {r['label']} | {r['status']} | {r['rows']} | {r['reason'][:120]} |" for r in public]
    (out / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="macOS 사용기록 읽기 전용 수집 + 소스별 수집 상태")
    ap.add_argument("--out", required=True, help="출력 폴더(보고서 옆 evidence/ 권장)")
    ap.add_argument("--days", type=int, help="최근 N일")
    ap.add_argument("--since", help="YYYY-MM-DD (포함)")
    ap.add_argument("--until", help="YYYY-MM-DD (미포함)")
    ap.add_argument("--request-access", action="store_true", help="권한 거부 소스가 있으면 전체 디스크 접근 권한 설정 창을 연다")
    ap.add_argument("--wait-access", type=int, default=0, help="권한 거부 소스를 N초 동안 다시 시도")
    ap.add_argument("--unified-log", action="store_true", help="통합 로그의 로그인/잠금 기록도 수집(최근 --days 또는 7일)")
    ap.add_argument("--home", default=str(Path.home()))
    a = ap.parse_args(argv)
    if sys.platform != "darwin" and a.home == str(Path.home()):
        print("macOS 전용 스크립트다", file=sys.stderr)
        return 2
    lo = hi = None
    if a.days:
        lo = time.time() - a.days * 86400
    if a.since:
        lo = datetime.strptime(a.since, "%Y-%m-%d").timestamp()
    if a.until:
        hi = datetime.strptime(a.until, "%Y-%m-%d").timestamp()
    window_text = f"{fmt(lo) if lo else '처음'} ~ {fmt(hi) if hi else '현재'}"
    sources = [dict(s) for s in SOURCES]
    if a.unified_log:
        next(s for s in sources if s["id"] == "unified_log")["fn"] = unified_log(a.days or 7)
    home = Path(a.home).expanduser()
    recs = [collect(s, home, (lo, hi)) for s in sources]
    denied = [r for r in recs if r["status"] == "DENIED"]
    if denied and a.request_access:
        subprocess.run(["open", FDA_PANE], check=False)
        print(f"[권한 요청] 시스템 설정 > 개인정보 보호 및 보안 > 전체 디스크 접근 권한에서 '{host_app()}' 을(를) 켜라. "
              f"거부된 소스: {', '.join(r['label'] for r in denied)}", file=sys.stderr)
    deadline = time.time() + a.wait_access
    while denied and time.time() < deadline:
        time.sleep(3)
        for i, r in enumerate(recs):
            if r["status"] == "DENIED":
                recs[i] = collect(next(s for s in sources if s["id"] == r["id"]), home, (lo, hi))
        denied = [r for r in recs if r["status"] == "DENIED"]
    if denied and (a.request_access or a.wait_access):
        print("[권한 요청] 아직 거부됨 — 권한을 켠 뒤 그 앱을 완전히 종료했다가 다시 열어야 적용되는 경우가 많다.", file=sys.stderr)
    write_outputs(Path(a.out), recs, window_text)
    for r in recs:
        print(f"{r['status']:8} {r['rows']:>7}  {r['label']}" + (f"  — {r['reason'][:100]}" if r["reason"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
