#!/usr/bin/env python3
"""query_evidence_db.py - 압수 SQLite DB 읽기전용 즉석 분석기 + 잔존 흔적 검색.

메신저 백업본·앱 데이터·브라우저 히스토리 같은 SQLite DB에서 SQL로 데이터를
추출하고, 삭제된 레코드가 페이지에 남긴 잔존 흔적을 키워드로 검색한다.

규율:
- **읽기전용 강제 (3중).** (1) DB는 file:...?mode=ro 로 열어 SQLite 수준에서
  쓰기를 원천 차단하고, (2) SELECT/PRAGMA/EXPLAIN/WITH 이외의 문은 접두어
  검사로 거부하며, (3) WITH로 시작하는 문은 본문에 DELETE/INSERT/UPDATE 같은
  변경 구문이 있으면 거부한다(SQLite는 CTE 부착 변경을 허용하므로).
- **흔적 검색은 복구가 아니다.** 잔존 스캔은 삭제된 레코드가 페이지에 남긴
  바이트를 찾을 뿐이며, VACUUM·secure_delete로 이미 지워졌으면 못 찾는다.
  "존재 증명"이 아니라 "부존재 증명도 아님" — 찾은 것만 보고한다.

Exit code: 0 완료 / 2 실행 오류 (파일 없음·금지된 문·SQLite 오류)
CLI:
    python scripts/query_evidence_db.py 증거.db --list-schema
    python scripts/query_evidence_db.py 증거.db --sql "SELECT * FROM messages LIMIT 50"
    python scripts/query_evidence_db.py 증거.db --keywords "회사명,010-1234-5678" -o 흔적.md
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sqlite3
import sys

# 원본 훼손 방지 — 이 네 가지로 시작하는 문만 허용한다.
_ALLOWED_PREFIXES = ("select", "pragma", "explain", "with")
# SQLite는 CTE(WITH)에 DELETE/INSERT/UPDATE를 붙이는 것을 허용한다:
#   WITH x AS (...) DELETE FROM t ...
# 따라서 WITH로 시작하는 문은 본문에 변경 키워드가 있으면 무조건 거부한다.
# (실 enforcement는 mode=ro이며, 이 검사는 깊이방어다.)
_WITH_MUTATION_RE = re.compile(
    r"\b(delete|insert|update|attach|detach|create|drop|alter|vacuum)\b", re.IGNORECASE
)
def sql_tokens(sql: str):
    i = 0
    while i < len(sql):
        start = i
        if sql.startswith("--", i):
            end = sql.find("\n", i)
            i = len(sql) if end < 0 else end
            yield "comment", sql[start:i]
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end < 0:
                raise ValueError("Unclosed SQL comment")
            i = end + 2
            yield "comment", sql[start:i]
        elif sql[i] in "'\"`[":
            closing = "]" if sql[i] == "[" else sql[i]
            i += 1
            while i < len(sql):
                if sql[i] == closing:
                    i += 1
                    if closing != "]" and i < len(sql) and sql[i] == closing:
                        i += 1
                        continue
                    break
                i += 1
            else:
                raise ValueError("Unclosed SQL quote")
            yield "quoted", sql[start:i]
        else:
            i += 1
            yield "code", sql[start:i]


_ENCODINGS = ("utf-8", "utf-16-le", "utf-16-be")
_CONTEXT_BYTES = 60
_CELL_LIMIT = 80
_SCAN_CHUNK = 8 * 1024 * 1024  # 압수 DB가 GB급이어도 통째로 메모리에 올리지 않는다


def open_readonly(db_path: str) -> sqlite3.Connection:
    """증거 DB를 절대 쓰지 않는 모드로 연다. URI 상대경로 이스케이프 주의.

    %를 먼저 이스케이프해야 한다 — SQLite URI는 %XX를 퍼센트 디코딩하므로,
    경로에 %가 있으면("100%20증거.db") 먼저 %25로 만들지 않으면 엉뚱한
    파일을 열거나 실패한다.
    """
    abs_path = os.path.abspath(db_path)
    abs_path = abs_path.replace("%", "%25").replace("?", "%3f").replace("#", "%23")
    uri = f"file:{abs_path}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _quote_ident(name: str) -> str:
    """SQLite 식별자 인용. 압수 DB의 테이블명은 신뢰할 수 없다(공격자 통제 가능)."""
    return '"' + name.replace('"', '""') + '"'


def strip_sql_comments(sql: str) -> str:
    """문자열·인용 식별자 내부는 건드리지 않고 주석만 제거한다.

    정규식 기반 치환은 `'a/*text*/b'` 같은 리터럴 내부의 `/* */`도 지워
    쿼리 의미를 바꾼다. 토크나이저로 quoted 세그먼트를 보존한다.
    """
    return "".join(" " if kind == "comment" else seg for kind, seg in sql_tokens(sql))


def check_statement(sql: str) -> str:
    """단일 문장 + 화이트리스트 접두어 검사. 위반 시 ValueError."""
    cleaned = strip_sql_comments(sql).strip().rstrip(";").strip()
    if not cleaned:
        raise ValueError("빈 SQL 문입니다")
    first = cleaned.split(None, 1)[0].lower()
    if first not in _ALLOWED_PREFIXES:
        raise ValueError(
            f"금지된 문입니다: {first.upper()} — 읽기전용 증거 DB에는 "
            f"SELECT/PRAGMA/EXPLAIN/WITH만 허용됩니다"
        )
    code = "".join(segment if kind == "code" else " " for kind, segment in sql_tokens(cleaned))
    if first == "with" and _WITH_MUTATION_RE.search(code):
        raise ValueError(
            "금지된 문입니다: WITH 접두 문에 변경 구문(DELETE/INSERT/UPDATE 등)이 "
            "포함되어 있습니다 — 읽기전용 증거 DB에서는 허용되지 않습니다"
        )
    return cleaned


def run_query(conn: sqlite3.Connection, sql: str, limit: int) -> tuple[list[str], list[list]]:
    cur = conn.execute(check_statement(sql))
    columns = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchmany(limit)
    return columns, [list(r) for r in rows]


def list_schema(conn: sqlite3.Connection) -> list[dict]:
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    out: list[dict] = []
    for table in tables:
        ident = _quote_ident(table)
        cols = conn.execute(f"PRAGMA table_info({ident})").fetchall()
        count = conn.execute(f"SELECT COUNT(*) FROM {ident}").fetchone()[0]
        out.append({
            "table": table,
            "columns": [(c[1], c[2]) for c in cols],
            "rows": count,
        })
    return out


def _printable_context(raw: bytes, start: int, length: int) -> str:
    lo = max(0, start - _CONTEXT_BYTES)
    hi = min(len(raw), start + length + _CONTEXT_BYTES)
    chunk = raw[lo:hi]
    text = chunk.decode("utf-8", errors="replace")
    text = "".join(ch if ch.isprintable() or ch in "\n\t" else "·" for ch in text)
    return text.replace("\n", " ")


def _sibling_label(path: str) -> str:
    for suffix in ("-wal", "-journal"):
        if path.endswith(suffix):
            return os.path.basename(path) + f" ({suffix.strip('-')})"
    return os.path.basename(path)


def _context_at(path: str, offset: int, length: int) -> str:
    """히트 1건의 주변 바이트를 파일에서 직접 읽어 컨텍스트를 만든다."""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, offset - _CONTEXT_BYTES))
            raw = f.read(length + 2 * _CONTEXT_BYTES)
    except OSError:
        return "(컨텍스트 읽기 실패)"
    return _printable_context(raw, min(offset, _CONTEXT_BYTES), length)


def _scan_file(path: str, prepared: list[tuple[str, list[tuple[str, bytes]]]],
               max_needle: int, hits: list[dict], seen: set) -> None:
    """파일을 청크로 읽으며 검색한다. 청크 경계에 걸친 needle은 tail+chunk
    버퍼에서 잡히고, 절대 오프셋으로 중복을 제거한다."""
    keep = max_needle + _CONTEXT_BYTES
    with open(path, "rb") as f:
        pos = 0  # 다음 buf[0]이 가리키는 파일 오프셋
        tail = b""
        while True:
            chunk = f.read(_SCAN_CHUNK)
            if not chunk:
                break
            buf = tail + chunk
            base = pos - len(tail)
            for keyword, needles in prepared:
                for enc, needle in needles:
                    start = 0
                    while True:
                        idx = buf.find(needle, start)
                        if idx < 0:
                            break
                        key = (path, keyword, base + idx, enc)
                        if key not in seen:
                            seen.add(key)
                            hits.append({
                                "file": _sibling_label(path),
                                "keyword": keyword,
                                "encoding": enc,
                                "offset": base + idx,
                                "context": _context_at(path, base + idx, len(needle)),
                            })
                        start = idx + 1
            tail = buf[-keep:]
            pos += len(chunk)


def scan_residual(db_path: str, keywords: list[str]) -> list[dict]:
    """파일 원시 바이트에서 키워드 잔존 흔적을 검색한다.

    본 파일과 -wal·-journal 동반 파일을 모두 본다. 삭제된 레코드가 아직
    재사용되지 않은 페이지에 남아 있으면 발견된다. GB급 압수 DB도 다룰 수
    있도록 파일을 통째로 메모리에 올리지 않고 청크로 읽는다.
    """
    siblings = [db_path]
    for suffix in ("-wal", "-journal"):
        if os.path.exists(db_path + suffix):
            siblings.append(db_path + suffix)

    prepared: list[tuple[str, list[tuple[str, bytes]]]] = []
    max_needle = 1
    for keyword in keywords:
        needles = [(enc, keyword.encode(enc, errors="ignore")) for enc in _ENCODINGS]
        needles = [(enc, n) for enc, n in needles if n]
        if needles:
            prepared.append((keyword, needles))
            max_needle = max(max_needle, *(len(n) for _, n in needles))

    hits: list[dict] = []
    seen: set[tuple] = set()
    for path in siblings:
        try:
            _scan_file(path, prepared, max_needle, hits, seen)
        except OSError as exc:
            print(f"[WARN] 읽기 실패 {path}: {exc}", file=sys.stderr)
            continue
    hits.sort(key=lambda h: (h["file"], h["keyword"], h["offset"]))
    return hits


def rows_to_markdown(columns: list[str], rows: list[list]) -> str:
    def cell(v) -> str:
        s = str(v) if v is not None else "(NULL)"
        s = s.replace("|", "\\|").replace("\n", " ")
        return s[:_CELL_LIMIT] + ("…" if len(s) > _CELL_LIMIT else "")

    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join(["---"] * len(columns)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(lines)


def rows_to_csv(columns: list[str], rows: list[list]) -> str:
    import io
    buf = io.StringIO()
    writer = csv.writer(buf)

    def safe_cell(v) -> str:
        s = str(v) if v is not None else ""
        # 압수 DB의 셀 값은 공격자가 통제할 수 있다. 엑셀에서 열 때 수식으로
        # 실행되는 값(=,+,@,탭 등)은 인용부호를 붙여 무력화한다. 음수는
        # 일반 숫자(-123)로 판단되면 그대로 둔다.
        if s and (s[0] in "=+@\t\r" or (s[0] == "-" and not re.match(r"^-\d+(\.\d+)?$", s))):
            s = "'" + s
        return s

    writer.writerow(columns)
    for row in rows:
        writer.writerow([safe_cell(v) for v in row])
    return buf.getvalue()


def render_report(schema: list[dict], query_block: str, hits: list[dict]) -> str:
    lines = ["# SQLite 증거 DB 분석 보고서\n"]

    if schema:
        lines.append("## 스키마\n")
        lines.append("| 테이블 | 행 수 | 열 |")
        lines.append("| :-- | ---: | :-- |")
        for t in schema:
            cols = ", ".join(f"{name}({typ})" for name, typ in t["columns"])
            lines.append(f"| {t['table']} | {t['rows']:,} | {cols} |")
        lines.append("")

    if query_block:
        lines.append("## 쿼리 결과\n")
        if query_block.startswith("```"):
            lines.append(query_block)  # 이미 펜스가 쳐진 기계 판독 형식
        else:
            lines.append(query_block)
        lines.append("")

    lines.append("## 잔존 흔적 검색 (삭제 레코드 잔존 바이트)\n")
    if hits:
        lines.append("| 파일 | 키워드 | 인코딩 | 오프셋 | 주변 내용 |")
        lines.append("| :-- | :-- | :-- | ---: | :-- |")
        for h in hits:
            lines.append(
                f"| {h['file']} | {h['keyword']} | {h['encoding']} | {h['offset']:,} | `{h['context']}` |"
            )
        lines.append(
            "\n> 잔존 흔적은 삭제된 데이터가 페이지에 남아 있음을 보여주는 참고 정보입니다. "
            "복구 보장이 아니며, VACUUM·secure_delete 이후에는 발견되지 않습니다. "
            "존재의 법적 의미는 포렌식 전문가 검토가 필요합니다."
        )
    else:
        lines.append("발견된 흔적 없음. (부존재의 증명이 아니다 — VACUUM 등으로 이미 덮였을 수 있습니다)")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="압수 SQLite DB 읽기전용 쿼리 + 잔존 흔적 검색")
    p.add_argument("db", help="SQLite DB 파일 경로")
    p.add_argument("--sql", default="", help="실행할 SELECT 문 (읽기전용 강제)")
    p.add_argument("--list-schema", action="store_true", help="테이블·열·행 수 나열")
    p.add_argument("--keywords", default="", help="쉼표 구분 잔존 흔적 키워드")
    p.add_argument("--format", choices=("md", "csv"), default="md", help="쿼리 결과 출력 형식 (기본 md)")
    p.add_argument("--limit", type=int, default=1000, help="쿼리 최대 행 수 (기본 1000)")
    p.add_argument("--output", "-o", default="", help="보고서 저장 경로 (미지정 시 stdout)")
    args = p.parse_args(argv)

    if not os.path.isfile(args.db):
        print(f"error: DB 파일을 찾을 수 없습니다: {args.db}", file=sys.stderr)
        return 2
    if not (args.sql or args.list_schema or args.keywords):
        print("error: --sql, --list-schema, --keywords 중 하나는 지정해야 합니다.", file=sys.stderr)
        return 2

    try:
        conn = open_readonly(args.db)
    except sqlite3.Error as exc:
        print(f"error: DB를 열지 못했습니다: {exc}", file=sys.stderr)
        return 2

    try:
        schema: list[dict] = []
        query_block = ""
        if args.list_schema:
            schema = list_schema(conn)
        if args.sql:
            columns, rows = run_query(conn, args.sql, args.limit)
            if args.format == "csv":
                # 기계 판독용 블록 — 보고서 안에서 ```csv 펜스로 추출 가능하게
                query_block = "```csv\n" + rows_to_csv(columns, rows) + "```"
            else:
                query_block = rows_to_markdown(columns, rows)
    except (ValueError, sqlite3.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        conn.close()
        return 2
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    hits = scan_residual(args.db, keywords) if keywords else []

    report = render_report(schema, query_block, hits)
    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[OK] 분석 보고서 저장: {args.output}")
    else:
        print(report)
    return 0


# ── 콘솔 하드닝 (#84) ───────────────────────────────────────────────
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import console as _console  # noqa: E402

if __name__ == "__main__":
    _console.force_utf8_console()
    raise SystemExit(main())
