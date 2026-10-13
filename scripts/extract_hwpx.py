#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_hwpx.py — HWPX 텍스트 추출기 (표준 라이브러리 전용)

HWPX는 ZIP 컨테이너 + XML이다. Contents/section*.xml 안의
<hp:t> 노드 텍스트를 순서대로 뽑아 평문을 만든다.
바이너리 HWP(.hwp, CFB 형식)는 이 도구로 읽지 않는다 —
그쪽은 외부 도구(obundh/korean-munseo-diff 등) 영역이다.

사용:
    python scripts/extract_hwpx.py doc.hwpx                  # 텍스트 출력
    python scripts/extract_hwpx.py dir/ -o out/              # 일괄 추출
    python scripts/extract_hwpx.py doc.hwpx --json           # 구조화 출력

알려진 한계:
- 표 셀 구조·서식은 잃는다. 텍스트 순서만 보존한다.
- 암호 걸린 HWPX는 ZIP 헤더도 못 열므로 실패로 보고한다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HWP_NS = "{http://www.hancom.co.kr/hwpml/2011/paragraph}"
SECTION_CAP = 8 * 1024 * 1024
TOTAL_CAP = 64 * 1024 * 1024
MEMBER_CAP = 10000
TEXT_CAP = 64 * 1024 * 1024


def extract_text(hwpx_path: Path) -> list[str]:
    """section XML들에서 <hp:t> 텍스트를 문서 순서대로 반환한다.

    리소스 상한: 섹션당 8MB, 문서 누적 64MB, 멤버 10,000개, 텍스트 64MB.
    초과 시 RuntimeError로 fail-closed — 지어내지 않는다.
    """
    if not zipfile.is_zipfile(hwpx_path):
        raise RuntimeError("HWPX가 아니거나 손상된 파일 (ZIP 시그니처 없음)")
    texts: list[str] = []
    text_len = 0
    with zipfile.ZipFile(hwpx_path) as zf:
        names = zf.namelist()
        if len(names) > MEMBER_CAP:
            raise RuntimeError(f"멤버 수 상한 초과 ({len(names)}>{MEMBER_CAP})")
        sections = sorted(
            (n for n in names
             if re.match(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.search(r"\d+", n).group(0)),
        )
        if not sections:
            raise RuntimeError("Contents/section*.xml이 없습니다")
        total = 0
        for name in sections:
            remaining = min(SECTION_CAP, TOTAL_CAP - total)
            info = zf.getinfo(name)
            if info.file_size > remaining:
                raise RuntimeError("Section or aggregate read limit exceeded")
            with zf.open(info) as stream:
                raw = stream.read(remaining + 1)
            if len(raw) > remaining:
                raise RuntimeError("Section or aggregate read limit exceeded")
            total += len(raw)
            if total > TOTAL_CAP:
                raise RuntimeError(f"문서 누적 크기 상한 초과 ({TOTAL_CAP}B) — 처리 중단")
            if len(raw) > SECTION_CAP:
                raise RuntimeError(f"섹션 크기 상한 초과: {name} ({len(raw)}B)")
            root = ET.fromstring(raw)
            for t in root.iter(f"{HWP_NS}t"):
                if t.text:
                    text_len += len(t.text.encode("utf-8"))
                    if text_len > TEXT_CAP:
                        raise RuntimeError(f"추출 텍스트 상한 초과 ({TEXT_CAP}B)")
                    texts.append(t.text)
    return texts


def process(path: Path) -> dict:
    try:
        texts = extract_text(path)
    except (RuntimeError, ET.ParseError, zipfile.BadZipFile, OSError) as e:
        return {"file": str(path), "status": "failed", "error": str(e)[:200]}
    return {
        "file": str(path),
        "status": "ok",
        "text_units": len(texts),
        "text": "\n".join(texts),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="HWPX 텍스트 추출 (stdlib 전용)")
    ap.add_argument("input", help=".hwpx 파일 또는 디렉터리")
    ap.add_argument("-o", "--outdir", default=None, help="디렉터리 입력 시 추출 텍스트 출력 위치")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)

    target = Path(args.input)
    if target.is_dir():
        files = sorted(target.rglob("*.hwpx"))
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2
    if not files:
        print(f".hwpx 파일이 없습니다: {target}", file=sys.stderr)
        return 2

    records = [process(f) for f in files]
    ok = sum(1 for r in records if r["status"] == "ok")

    if args.outdir:
        outdir = Path(args.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        for f, r in zip(files, records):
            if r["status"] == "ok":
                (outdir / (f.stem + ".txt")).write_text(r["text"], encoding="utf-8")
        print(f"추출 완료: {ok}/{len(files)}개 → {outdir}")
    elif args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        for r in records:
            if r["status"] == "ok":
                print(f"=== {r['file']} ({r['text_units']} units) ===")
                print(r["text"])
            else:
                print(f"[FAIL] {r['file']}: {r['error']}", file=sys.stderr)

    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
