#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sqlite_survey.py — SQLite 증거 DB 표면 조사 (stdlib 전용, 읽기 전용)

증거 폴더 안의 SQLite 파일(카카오톡·Chrome·각종 앱 DB)을
읽기 전용 + immutable 모드로 열어 구조만 조사한다:
- 테이블 목록과 행 수
- integrity_check 결과
- 페이지 크기/수, 스키마 버전
- 테이블별 컬럼 목록 (내용은 안 읽음)

중요: immutable 모드로 열어 -wal/-shm 부수 파일 생성이나
저널 롤백 등 원본 변경 가능성을 원천 차단한다.

사용:
    python scripts/sqlite_survey.py evidence/
    python scripts/sqlite_survey.py chats.db --json
    python scripts/sqlite_survey.py chats.db --sample 테이블명 3   # 표본 행 확인

알려진 한계:
- 스키마·행 수만 본다 — 내용 해석(어느 컬럼이 메시지인지)은 수동.
- 손상된 DB는 integrity_check가 실패로 보고한다 — 복구는 별도 도구.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import urllib.parse
from pathlib import Path

SQLITE_EXTS = {".db", ".sqlite", ".sqlite3", ".db3"}
_MAGIC = b"SQLite format 3\x00"  # 정확히 16바이트 헤더


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == _MAGIC
    except OSError:
        return False


def connect_ro(path: Path) -> sqlite3.Connection:
    """immutable 읽기 전용 연결 — 원본·-wal·-shm을 절대 건드리지 않는다.
    파일명의 ?·#·공백 등이 URI 파싱을 깨지 못하게 인코딩한다."""
    uri = "file:" + urllib.parse.quote(str(path.resolve())) + "?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def survey_db(path: Path, sample: tuple[str, int] | None = None) -> dict:
    rec: dict = {"file": str(path), "sha256": sha256_file(path),
                 "size_bytes": path.stat().st_size, "is_sqlite": is_sqlite(path)}
    if not rec["is_sqlite"]:
        rec["error"] = "SQLite 매직 없음 — 일반 파일이거나 다른 DB 형식"
        return rec
    try:
        conn = connect_ro(path)
    except sqlite3.Error as e:
        rec["error"] = f"열기 실패: {e}"
        return rec
    try:
        cur = conn.cursor()
        rec["page_size"] = cur.execute("PRAGMA page_size").fetchone()[0]
        rec["page_count"] = cur.execute("PRAGMA page_count").fetchone()[0]
        integ = cur.execute("PRAGMA integrity_check").fetchone()[0]
        rec["integrity"] = integ
        rec["integrity_ok"] = (integ == "ok")

        tables = []
        rows = cur.execute(
            "SELECT name, type FROM sqlite_master "
            "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name").fetchall()
        for name, ttype in rows:
            entry: dict = {"name": name, "type": ttype}
            try:
                entry["row_count"] = cur.execute(
                    f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            except sqlite3.Error as e:
                entry["row_count"] = None
                entry["count_error"] = str(e)
            try:
                entry["columns"] = [r[1] for r in cur.execute(
                    f'PRAGMA table_info("{name}")').fetchall()]
            except sqlite3.Error:
                entry["columns"] = []
            if sample and sample[0] == name:
                try:
                    entry["sample_rows"] = [
                        list(r) for r in cur.execute(
                            f'SELECT * FROM "{name}" LIMIT ?', (sample[1],)).fetchall()]
                except sqlite3.Error as e:
                    entry["sample_error"] = str(e)
            tables.append(entry)
        rec["tables"] = tables
        rec["total_rows"] = sum(t["row_count"] or 0 for t in tables)
    except sqlite3.Error as e:
        rec["error"] = f"조사 실패: {e}"
    finally:
        conn.close()
    return rec


def scan(root: Path) -> list[dict]:
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        if p.suffix.lower() in SQLITE_EXTS or is_sqlite(p):
            out.append(survey_db(p))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SQLite 증거 DB 표면 조사 (읽기 전용)")
    ap.add_argument("target", help="DB 파일 또는 디렉터리")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--sample", nargs=2, metavar=("테이블", "행수"),
                    help="특정 테이블의 표본 행 N개 확인")
    args = ap.parse_args(argv)

    sample = (args.sample[0], int(args.sample[1])) if args.sample else None
    target = Path(args.target)
    if target.is_dir():
        records = scan(target)
    elif target.is_file():
        records = [survey_db(target, sample)]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"db_files": len(records), "records": records},
                         ensure_ascii=False, indent=2, default=str))
    else:
        for r in records:
            if not r.get("is_sqlite") or "error" in r and "tables" not in r:
                print(f"[실패] {r['file']}: {r.get('error', '')}")
                continue
            mark = "ok" if r["integrity_ok"] else "손상!"
            print(f"{r['file']}: 테이블 {len(r['tables'])}개, "
                  f"총 {r['total_rows']}행, 무결성={mark}")
            for t in r["tables"]:
                print(f"  {t['name']} ({t['type']}): {t.get('row_count')}행, "
                      f"컬럼 {len(t.get('columns', []))}개")
                for row in t.get("sample_rows", []):
                    print(f"    표본: {row}")
    broken = [r for r in records if r.get("is_sqlite") and not r.get("integrity_ok")]
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
