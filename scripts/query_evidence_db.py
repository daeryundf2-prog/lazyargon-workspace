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
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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


_AXIOM_ALIASES: dict[str, str] = {
    "Storage Device Events": "Windows Event Logs - Storage Device Events",
    "User PNP Events": "Windows Event Logs - User PNP Events",
    "Prefetch Files": "Prefetch Files - Windows 8/10/11",
    "Prefetch": "Prefetch Files - Windows 8/10/11",
    "OS Info": "Operating System Information",
    "File System Info": "File System Information",
    "Chromium Downloads": "Chromium Based Browsers Downloads",
    "Chromium Web History": "Chromium Based Browsers Web History",
}
from axiom_insider_audit import (  # noqa: E402
    export_axiom_counts,
    fetch_axiom_v10_hits,
    get_axiom_canonical_artifacts,
    has_axiom_v10_schema,
    scan_git_and_utf16,
    scan_insider_prompts,
)

_CORRECTION_LINE_RE = re.compile(r"오류|오기|정정|아니라|실제로는|잘못\s*(?:인용|혼입|매핑)")
_HIT_CITATION_RE = re.compile(
    r"\bhits?(?:_id)?(?:\s*[=:#]\s*|\s+)[`'*]*(\d+)(?!,\d{3}\b)[`'*]*((?:\s*(?:,\s+|/|\xb7)\s*[`'*]*\d+(?!,\d{3}\b)[`'*]*)*)",
    re.IGNORECASE,
)


def _artifact_compatible(claimed: str, actual: str) -> bool:
    c, a = claimed.casefold(), actual.casefold()
    if c == a or a.startswith(c + " "):
        return True
    c_norm = c.replace("chromium based browsers ", "chrome ")
    a_norm = a.replace("chromium based browsers ", "chrome ")
    if c_norm == a_norm:
        return True
    if {c, a} <= {"windows stored credentials", "passwords and tokens"}:
        return True
    return False


def verify_axiom_hits(conn: sqlite3.Connection, hit_ids: list[int]) -> dict[int, dict]:
    """Magnet AXIOM Case.mfdb에서 지정한 hit_id 목록의 실제 artifact_name과 핵심 fragment를 조회한다."""
    if not hit_ids:
        return {}
    if has_axiom_v10_schema(conn):
        return fetch_axiom_v10_hits(conn, hit_ids)
    uniq = sorted({int(x) for x in hit_ids if int(x) > 0})
    placeholders = ",".join("?" for _ in uniq)
    rows = conn.execute(
        f"SELECT h.id, h.source_id, a.name FROM hit h "
        f"JOIN artifact_version av ON h.artifact_version_id = av.id "
        f"JOIN artifact a ON av.artifact_id = a.id WHERE h.id IN ({placeholders})",
        uniq,
    ).fetchall()
    out: dict[int, dict] = {}
    for hid, sid, aname in rows:
        frags = conn.execute(
            "SELECT name, value FROM hit_fragment WHERE hit_id = ? LIMIT 6", (hid,)
        ).fetchall()
        out[int(hid)] = {
            "hit_id": int(hid),
            "source_id": int(sid) if sid is not None else None,
            "artifact_name": str(aname),
            "fragments": {str(k): str(v)[:120] for k, v in frags if v is not None and str(v).strip()},
        }
    return out


def verify_report_axiom_citations(conn: sqlite3.Connection, report_text: str) -> dict:
    """보고서 본문에 인용된 hit <ID>와 인접 아티팩트 분류명을 Case.mfdb 원본과 1:1 대조한다."""
    canonical_names = get_axiom_canonical_artifacts(conn)
    canon_map = {n.casefold(): n for n in canonical_names}
    search_terms: list[tuple[str, str]] = [(n, n) for n in canonical_names]
    for alias, target in _AXIOM_ALIASES.items():
        resolved = canon_map.get(target.casefold(), target)
        search_terms.append((alias, resolved))
    search_terms.sort(key=lambda x: len(x[0]), reverse=True)
    term_res = [
        (re.compile(rf"(?<![A-Za-z0-9_\\/]){re.escape(term)}(?![A-Za-z0-9_\\/])", re.IGNORECASE), canon)
        for term, canon in search_terms
    ]

    line_citations: list[tuple[int, str, list[tuple[int, int]]]] = []
    all_hit_ids: set[int] = set()
    in_correction_sec = False
    for idx, line in enumerate(report_text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            in_correction_sec = bool(_CORRECTION_LINE_RE.search(line))
        cits: list[tuple[int, int]] = []
        for m in _HIT_CITATION_RE.finditer(line):
            g_start = m.start()
            first_id = int(m.group(1))
            cits.append((g_start, first_id))
            all_hit_ids.add(first_id)
            tail = m.group(2) or ""
            for tm in re.finditer(r"(\d+)", tail):
                tid = int(tm.group(1))
                cits.append((g_start, tid))
                all_hit_ids.add(tid)
        if cits and not in_correction_sec and not _CORRECTION_LINE_RE.search(line):
            line_citations.append((idx, line, cits))

    verified = verify_axiom_hits(conn, sorted(all_hit_ids))
    missing_hits = sorted(all_hit_ids - set(verified.keys()))
    mismatches: list[dict] = []

    for line_no, line, cits in line_citations:
        spans: list[tuple[int, int, str]] = []
        for rx, canon in term_res:
            for m in rx.finditer(line):
                s, e = m.span()
                if not any(es <= s < ee or es < e <= ee for es, ee, _ in spans):
                    spans.append((s, e, canon))
        if not spans:
            continue
        spans.sort(key=lambda x: x[0])
        for g_start, hid in cits:
            if hid not in verified:
                continue
            actual = verified[hid]["artifact_name"]
            preceding = [
                sp for sp in spans
                if sp[1] <= g_start and re.fullmatch(r"[\s`*':(-]*", line[sp[1] : g_start])
            ]
            if not preceding:
                continue
            chosen = preceding[-1][2]
            if not _artifact_compatible(chosen, actual):
                mismatches.append({
                    "line": line_no,
                    "hit_id": hid,
                    "claimed_artifact": chosen,
                    "actual_artifact": actual,
                })

    return {
        "ok": len(missing_hits) == 0 and len(mismatches) == 0,
        "total_cited_hits": len(all_hit_ids),
        "verified_hits_count": len(verified),
        "missing_hits": missing_hits,
        "mismatches": mismatches,
        "qa_ids": {str(hid): info["artifact_name"] for hid, info in sorted(verified.items())},
        "hits": verified,
    }


def main(argv: list[str] | None = None) -> int:
    import json

    p = argparse.ArgumentParser(description="압수 SQLite DB 읽기전용 쿼리 + 잔존 흔적 검색 + AXIOM hit 검증")
    p.add_argument("db", help="SQLite DB 파일 경로")
    p.add_argument("--sql", default="", help="실행할 SELECT 문 (읽기전용 강제)")
    p.add_argument("--list-schema", action="store_true", help="테이블·열·행 수 나열")
    p.add_argument("--keywords", default="", help="쉼표 구분 잔존 흔적 키워드")
    p.add_argument("--verify-hits", default="", help="쉼표 구분 AXIOM hit_id 목록 실존·분류명 조회")
    p.add_argument("--verify-report", default="", help="보고서(.md) 내 인용된 hit_id와 아티팩트 분류명을 DB 원본과 대조")
    p.add_argument("--export-axiom-counts", default="", help="AXIOM 전체 아티팩트 건수(artifact_counts.txt) 저장 디렉터리")
    p.add_argument("--scan-insider-prompts", action="store_true", help="AI 프롬프트(Claude Command History) 배임·은폐 지시 스캔")
    p.add_argument("--scan-git-dir", default="", help="마운트된 디렉터리 내 원본 .git(원격푸시 vs 로컬커밋 분리) 및 UTF-16 스캔")
    p.add_argument("--json", action="store_true", help="검증·스캔 결과를 JSON으로 출력")
    p.add_argument("--format", choices=("md", "csv"), default="md", help="쿼리 결과 출력 형식 (기본 md)")
    p.add_argument("--limit", type=int, default=1000, help="쿼리 최대 행 수 (기본 1000)")
    p.add_argument("--output", "-o", default="", help="보고서 저장 경로 (미지정 시 stdout)")
    args = p.parse_args(argv)

    if args.scan_git_dir and not os.path.isfile(args.db):
        res = scan_git_and_utf16(args.scan_git_dir)
        out_str = json.dumps(res, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(out_str + "\n")
        else:
            print(out_str)
        return 0

    if not os.path.isfile(args.db):
        print(f"error: DB 파일을 찾을 수 없습니다: {args.db}", file=sys.stderr)
        return 2
    if not (
        args.sql or args.list_schema or args.keywords or args.verify_hits
        or args.verify_report or args.export_axiom_counts or args.scan_insider_prompts or args.scan_git_dir
    ):
        print(
            "error: 실행 옵션(--sql, --list-schema, --keywords, --verify-hits, --verify-report 등)을 지정해야 합니다.",
            file=sys.stderr,
        )
        return 2

    try:
        conn = open_readonly(args.db)
    except sqlite3.Error as exc:
        print(f"error: DB를 열지 못했습니다: {exc}", file=sys.stderr)
        return 2

    try:
        if args.export_axiom_counts or args.scan_insider_prompts or args.scan_git_dir:
            payload: dict = {}
            if args.export_axiom_counts:
                counts = export_axiom_counts(conn, args.export_axiom_counts)
                payload["artifact_counts"] = len(counts)
            if args.scan_insider_prompts:
                payload["insider_prompts"] = scan_insider_prompts(conn)
            if args.scan_git_dir:
                payload["git_and_utf16"] = scan_git_and_utf16(args.scan_git_dir)
            out_str = json.dumps(payload, ensure_ascii=False, indent=2)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(out_str + "\n")
            else:
                print(out_str)
            return 0
        if args.verify_hits or args.verify_report:
            if args.verify_report:
                if not os.path.isfile(args.verify_report):
                    print(f"error: 보고서 파일을 찾을 수 없습니다: {args.verify_report}", file=sys.stderr)
                    return 2
                with open(args.verify_report, "r", encoding="utf-8", errors="replace") as rf:
                    rep_text = rf.read()
                res = verify_report_axiom_citations(conn, rep_text)
            else:
                req_ids = [int(x.strip()) for x in re.split(r"[\s,]+", args.verify_hits) if x.strip().isdigit()]
                verified = verify_axiom_hits(conn, req_ids)
                missing = sorted(set(req_ids) - set(verified.keys()))
                res = {
                    "ok": len(missing) == 0,
                    "total_cited_hits": len(set(req_ids)),
                    "verified_hits_count": len(verified),
                    "missing_hits": missing,
                    "mismatches": [],
                    "hits": verified,
                }
            if args.json:
                out_str = json.dumps(res, ensure_ascii=False, indent=2)
            else:
                lines = [
                    f"[{'PASS' if res['ok'] else 'FAIL'}] AXIOM hit 검증: "
                    f"인용 {res['total_cited_hits']}건 중 {res['verified_hits_count']}건 실존 확인"
                ]
                for mid in res["missing_hits"]:
                    lines.append(f"  - MISSING: hit {mid} (DB에 존재하지 않음)")
                for mm in res["mismatches"]:
                    lines.append(
                        f"  - MISMATCH (line {mm['line']}): hit {mm['hit_id']} "
                        f"보고서 표기='{mm['claimed_artifact']}' != DB 실제='{mm['actual_artifact']}'"
                    )
                for hid, info in sorted(res["hits"].items()):
                    lines.append(f"  - hit {hid} (source_id={info['source_id']}): [{info['artifact_name']}] {info['fragments']}")
                out_str = "\n".join(lines)
            if args.output:
                os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(out_str + "\n")
            else:
                print(out_str)
            return 0 if res["ok"] else 1

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
