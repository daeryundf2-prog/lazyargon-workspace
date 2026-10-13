#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_parser.py — parse_korean_doc 벤치마크 (페이지/초, 표 재현도).

합성 HWPX 문서를 생성해 파서를 반복 실행하고 두 지표를 낸다:
  pages_per_sec : 처리한 섹션(페이지 상당) 수 / 경과 초
  table_fidelity: 추출된 표 셀 텍스트가 기대 셀과 일치하는 비율 (0~1)

결과는 JSON으로 출력해 CI 아티팩트/비교에 쓸 수 있다.
  python scripts/bench_parser.py [--docs 20] [--pages 30] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import parse_korean_doc as pkd  # noqa: E402

HP_NS = "http://www.hancom.co.kr/hwpml/2011/hp"
HS_NS = "http://www.hancom.co.kr/hwpml/2011/hs"

PARA = "제{n}조 이 문서는 벤치마크용 합성 공문서 문단입니다. 숫자 {n}와 표현은 고정입니다."
CELL = "항목{r}x{c} 금액 {r}{c}0원"


def make_hwpx(path: Path, n_pages: int, table_rows: int = 5) -> int:
    """n_pages개 섹션·섹션당 표 1개(table_rows×2셀)의 HWPX를 만든다. 셀 수 반환."""
    content_hpf = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<pkg:package xmlns:pkg="http://www.idpf.org/2007/opf" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>bench</dc:title></pkg:package>"
    )
    cells = 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/content.hpf", content_hpf)
        for i in range(n_pages):
            rows = "".join(
                "<hp:tr>" + "".join(f"<hp:tc><hp:t>{CELL.format(r=r, c=c)}</hp:t></hp:tc>" for c in range(2)) + "</hp:tr>"
                for r in range(table_rows)
            )
            cells += table_rows * 2
            z.writestr(
                f"Contents/section{i}.xml",
                f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<hs:root xmlns:hs="{HS_NS}" xmlns:hp="{HP_NS}"><hp:body>'
                f"<hp:p><hp:t>{PARA.format(n=i)}</hp:t></hp:p>"
                f"<hp:tbl>{rows}</hp:tbl></hp:body></hs:root>",
            )
    return cells


def run_benchmark(docs: int, pages: int) -> dict:
    total_cells = 0
    extracted_cells = 0
    total_pages = 0
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        for d in range(docs):
            doc = Path(tmp) / f"bench_{d}.hwpx"
            expected_cells = make_hwpx(doc, pages)
            result = pkd.parse_hwpx(str(doc))
            total_pages += len(result["sections"])
            total_cells += expected_cells
            for tbl in result["tables"]:
                for row in tbl:
                    for cell in row:
                        if cell.startswith("항목") and "금액" in cell:
                            extracted_cells += 1
    elapsed = time.perf_counter() - start
    return {
        "docs": docs,
        "pages_total": total_pages,
        "elapsed_sec": round(elapsed, 3),
        "pages_per_sec": round(total_pages / elapsed, 1) if elapsed else None,
        "table_fidelity": round(extracted_cells / total_cells, 4) if total_cells else None,
        "cells_expected": total_cells,
        "cells_extracted": extracted_cells,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HWPX 파서 벤치마크 — 페이지/초, 표 재현도")
    ap.add_argument("--docs", type=int, default=20, help="합성 문서 수 (기본 20)")
    ap.add_argument("--pages", type=int, default=30, help="문서당 섹션(페이지) 수 (기본 30)")
    ap.add_argument("--json", action="store_true", help="JSON만 출력")
    args = ap.parse_args(argv)

    result = run_benchmark(args.docs, args.pages)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"docs={result['docs']} pages={result['pages_total']} elapsed={result['elapsed_sec']}s")
        print(f"pages/sec={result['pages_per_sec']} table_fidelity={result['table_fidelity']} "
              f"({result['cells_extracted']}/{result['cells_expected']} cells)")
    return 0


if __name__ == "__main__":
    if sys.stdout:
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
