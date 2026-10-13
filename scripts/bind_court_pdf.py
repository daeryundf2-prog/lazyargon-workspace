#!/usr/bin/env python3
"""bind_court_pdf.py - 전자소송 제출용 증거 PDF 종합 바인더.

표찰된 갑/을호증 PDF 여러 건을 호증별 북마크(계층형 TOC)를 넣어 한 권으로
병합하고, 전자소송(ECFS) 파일 용량 한계(기본 50MB)를 넘으면 자동으로 권을
나눈다. 병합 순서·북마크는 증거 목록 JSON의 순서를 따른다.

입력 JSON (증거설명서 evidence.json과 호환):
[
  {"label": "갑 제1호증", "title": "차용증", "file": "갑제1호증.pdf"},
  {"label": "갑 제2호증", "title": "내용증명", "file": "갑제2호증.pdf"}
]

Exit code: 0 완료 / 2 실행 오류 (파일 없음·빈 목록 등)
CLI:
    python scripts/bind_court_pdf.py --input-json evidence.json -o 증거바인더.pdf
    python scripts/bind_court_pdf.py --input-json evidence.json -o 바인더.pdf --max-mb 50
"""

from __future__ import annotations

import argparse
import json
import os
import sys

MAX_MB_DEFAULT = 50  # ECFS 개별 첨부파일 용량 한계 기준


def load_items(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):  # 증거설명서 형식과의 호환 (evidence_list 키)
        data = data.get("evidence_list", [])
    items: list[dict] = []
    for entry in data:
        file = entry.get("file") or entry.get("file_path") or entry.get("path")
        if not file:
            raise ValueError(f"증거 항목에 file 경로가 없습니다: {entry}")
        items.append({
            "file": file,
            "label": str(entry.get("label", "")).strip(),
            "title": str(entry.get("title", "")).strip(),
        })
    if not items:
        raise ValueError("증거 항목이 비어 있습니다")
    return items


def bind_volumes(items: list[dict], max_bytes: int) -> list[dict]:
    """증거 PDF를 용량 한계에 맞춰 권으로 묶는다.

    권 경계 판정은 원본 파일 크기의 누적으로 한다(압축 후 크기와 다소 차이가
    나지만, 한계의 50MB는 여유가 크므로 보수적으로 안전하다).
    """
    from dep_help import require
    require("fitz")
    import fitz  # PyMuPDF

    for item in items:
        if not os.path.isfile(item["file"]):
            raise FileNotFoundError(f"증거 PDF를 찾을 수 없습니다: {item['file']}")

    volumes: list[dict] = []
    current: dict = {"items": [], "size": 0}
    for item in items:
        size = os.path.getsize(item["file"])
        if current["items"] and current["size"] + size > max_bytes:
            volumes.append(current)
            current = {"items": [], "size": 0}
        current["items"].append(item)
        current["size"] += size
    if current["items"]:
        volumes.append(current)

    for volume in volumes:
        doc = fitz.open()
        toc: list[list] = []
        for item in volume["items"]:
            with fitz.open(item["file"]) as src:
                start = len(doc) + 1
                doc.insert_pdf(src)
            label = " ".join(part for part in (item["label"], item["title"]) if part)
            toc.append([1, label or os.path.basename(item["file"]), start])
        doc.set_toc(toc)
        volume["doc"] = doc
        volume["pages"] = len(doc)
    return volumes


def volume_path(output: str, index: int, total: int) -> str:
    if total == 1:
        return output
    stem, ext = os.path.splitext(output)
    return f"{stem}_{index}권{ext}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="증거 PDF 병합 바인더 (북마크 + 용량 자동 분할)")
    p.add_argument("--input-json", "-i", required=True, help="증거 목록 JSON (label/title/file)")
    p.add_argument("--output", "-o", required=True, help="바인더 PDF 경로 (분할 시 _N권 접미)")
    p.add_argument("--max-mb", type=float, default=MAX_MB_DEFAULT, help="권당 최대 용량 MB (기본 50, ECFS 기준)")
    args = p.parse_args(argv)

    if not os.path.isfile(args.input_json):
        print(f"error: 증거 목록 JSON을 찾을 수 없습니다: {args.input_json}", file=sys.stderr)
        return 2
    try:
        items = load_items(args.input_json)
    except json.JSONDecodeError as exc:
        print(f"error: JSON 파싱 실패: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        volumes = bind_volumes(items, int(args.max_mb * 1024 * 1024))
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: PDF 병합 실패: {exc}", file=sys.stderr)
        return 2

    out_dir = os.path.dirname(os.path.abspath(args.output))
    os.makedirs(out_dir, exist_ok=True)
    total = len(volumes)
    for i, volume in enumerate(volumes, 1):
        path = volume_path(args.output, i, total)
        volume["doc"].save(path, garbage=4, deflate=True)
        volume["doc"].close()
        size_mb = os.path.getsize(path) / (1024 * 1024)
        print(f"[OK] 권 {i}/{total}: {path} ({volume['pages']}페이지, {size_mb:.1f}MB)")
        for item in volume["items"]:
            print(f"    - {item['label']} {item['title']}")

    if total > 1:
        print(f"[i] {total}권으로 분할 — 전자소송 업로드 시 각 권을 별도 첨부하십시오.")
    return 0


# ── 콘솔 하드닝 (#84) ───────────────────────────────────────────────
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import console as _console  # noqa: E402

if __name__ == "__main__":
    _console.force_utf8_console()
    raise SystemExit(main())
