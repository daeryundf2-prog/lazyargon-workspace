#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
keyword_report.py — 증거형 키워드 검색 리포트

"해당 키워드가 있는가"를 grep 결과가 아니라 감정서에 붙일 수 있는
형태로 만든다: 파일 경로 + 줄 번호 + 원문 + 검색 대상 파일의 SHA-256.
'없음'도 '검색 안 함'이 아니라 'N개 파일 전수 검색 결과 미검출'로
기록한다 — 부재 증명에 필요한 검색 범위가 보고서에 남는다.

사용:
    python scripts/keyword_report.py evidence/ "보이스피싱" "계좌이체"
    python scripts/keyword_report.py dir/ 키워드 --context 2 --json
    python scripts/keyword_report.py dir/ 키워드 -o report.json

알려진 한계:
- 리터럴 문자열 검색이다. OCR 오류·유사표현·이미지 속 글자는
  잡지 못한다. 유의어 확장 검색은 이 도구의 역할이 아니다.
- 바이너리 파일은 건너뛴다 (읽기 실패 파일은 skipped로 기록).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

TEXT_EXTS = {
    ".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".html", ".htm",
    ".log", ".ini", ".cfg", ".yaml", ".yml", ".py", ".js", ".mjs",
    ".java", ".c", ".cpp", ".h", ".sh", ".ps1", ".sql",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def search_file_result(path: Path, keywords: list[str], context: int) -> tuple[list[dict], str | None]:
    """(히트 목록, 오류 문자열|None)을 반환한다. 읽기 실패는 None 히트가 아니라 오류로 보고한다."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return [], str(e)
    hits = []
    for i, line in enumerate(lines):
        for kw in keywords:
            if kw in line:
                hit = {
                    "line": i + 1,
                    "keyword": kw,
                    "text": line.strip(),
                }
                if context:
                    lo = max(0, i - context)
                    hi = min(len(lines), i + context + 1)
                    hit["context"] = [
                        {"line": j + 1, "text": lines[j].strip()}
                        for j in range(lo, hi) if j != i
                    ]
                hits.append(hit)
                break  # 같은 줄에서 키워드 여러 개면 한 번만
    return hits, None


def search_file(path: Path, keywords: list[str], context: int) -> list[dict]:
    hits, error = search_file_result(path, keywords, context)
    if error is not None:
        raise OSError(error)
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="증거형 키워드 검색 리포트 (로컬 전용)")
    ap.add_argument("target", help="검색 대상 파일 또는 디렉터리")
    ap.add_argument("keywords", nargs="+", help="검색할 키워드(리터럴)")
    ap.add_argument("--context", type=int, default=0, help="히트 전후 맥락 줄 수")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("-o", "--output", default=None, help="리포트 출력 경로")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.is_file())
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2

    searched, skipped, results = [], [], []
    read_errors = []
    for f in files:
        if f.suffix.lower() not in TEXT_EXTS:
            skipped.append(str(f))
            continue
        hits, error = search_file_result(f, args.keywords, args.context)
        if error is not None:
            skipped.append(str(f))
            read_errors.append({"file": str(f), "error": error[:200]})
            continue
        searched.append(str(f))
        if hits:
            results.append({
                "file": str(f),
                "sha256": sha256_file(f),
                "hit_count": len(hits),
                "hits": hits,
            })

    report = {
        "keywords": args.keywords,
        "scope": str(target),
        "files_searched": len(searched),
        "files_skipped_binary": len(skipped),
        "files_read_failed": len(read_errors),
        "read_errors": read_errors[:50],
        "files_with_hits": len(results),
        "total_hits": sum(r["hit_count"] for r in results),
        "results": results,
        "skipped": skipped[:50],
    }

    if args.json or args.output:
        out = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            Path(args.output).write_text(out, encoding="utf-8")
            print(f"→ {args.output}")
        if args.json:
            print(out)
    else:
        if results:
            for r in results:
                print(f"{r['file']}  (sha256:{r['sha256'][:16]}…)  {r['hit_count']}히트")
                for h in r["hits"]:
                    print(f"    L{h['line']}  [{h['keyword']}]  {h['text'][:120]}")
        print(f"\n검색 {report['files_searched']}개 파일(바이너리/읽기실패 {report['files_skipped_binary']}개 제외), "
              f"히트 {report['total_hits']}건 / {report['files_with_hits']}개 파일")
        if report["files_read_failed"]:
            print(f"주의: 읽기 실패 {report['files_read_failed']}개 파일 — '미검출'이 아니라 '검색 불가'다", file=sys.stderr)
        if report["total_hits"] == 0:
            print("결과: 전수 검색 범위 내 미검출")

    return 1 if report["total_hits"] == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
