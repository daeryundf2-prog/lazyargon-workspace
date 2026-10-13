#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_korean_doc.py - HWP/HWPX/PDF 한국 공문서 텍스트 및 메타데이터 추출 엔진
"""

import os
import sys
import json
import argparse
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


def _escape_md_cell(text: str) -> str:
    """Escape pipe and newlines for markdown table cells."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _local_name(tag: str) -> str:
    """Strip XML namespace: '{uri}name' -> 'name'. Names without braces pass through."""
    return tag.rsplit("}", 1)[-1]


def _findall_local(root, local_name: str) -> list:
    """Namespace-agnostic findall: match elements by local tag name.

    HWPX(OWPML) 문서는 한컴 버전에 따라 네임스페이스 URI가 다를 수 있으므로
    (예: http://www.hancom.co.kr/hwpml/2011/hp) 로컬 이름으로 매칭한다.
    """
    return [el for el in root.iter() if _local_name(el.tag) == local_name]


def _natural_sort_key(name: str):
    """'section10.xml'이 'section2.xml'보다 뒤로 가도록 숫자 구간을 정수로 비교."""
    import re
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name)]


DC_ELEMENTS = {
    "title", "creator", "subject", "description", "publisher",
    "contributor", "date", "type", "format", "identifier",
    "source", "language", "relation", "coverage", "rights", "keyword",
}


def _parse_dc_metadata(content_hpf_data: bytes) -> dict:
    """content.hpf에서 Dublin Core 메타데이터 추출 (네임스페이스 무관, 로컬 이름 매칭)."""
    metadata = {}
    try:
        tree = ET.fromstring(content_hpf_data)
    except Exception as e:
        return {"_warning": f"Failed to parse content.hpf: {e}"}
    for elem in tree.iter():
        local = _local_name(elem.tag)
        if local in DC_ELEMENTS and elem.text and elem.text.strip() and local not in metadata:
            metadata[local] = elem.text.strip()
    return metadata


def parse_hwpx(file_path: str) -> dict:
    """순수 파이썬 ZIP/XML 기반 HWPX 파서 (한컴 오피스/JVM 무설치 지원)"""
    result = {
        "file_path": file_path,
        "format": "HWPX (OWPML)",
        "sections": [],
        "text": "",
        "tables": [],
        "metadata": {}
    }

    with zipfile.ZipFile(file_path, 'r') as z:
        # 1. 메타데이터 (Contents/content.hpf — Dublin Core, 네임스페이스 무관 매칭)
        if "Contents/content.hpf" in z.namelist():
            result["metadata"] = _parse_dc_metadata(z.read("Contents/content.hpf"))

        # 2. 본문 섹션 (Contents/section0.xml, section1.xml ...) — 자연 정렬
        section_files = sorted(
            [f for f in z.namelist() if f.startswith("Contents/section") and f.endswith(".xml")],
            key=_natural_sort_key,
        )
        if not section_files:
            result["metadata"]["_warning"] = "No section XML found in HWPX"
        full_text_chunks = []

        for s_file in section_files:
            try:
                xml_data = z.read(s_file)
                tree = ET.fromstring(xml_data)
            except Exception as e:
                print(f"[WARN] Failed to parse {s_file}: {e}", file=sys.stderr)
                continue

            # 표 추출 대상을 먼저 수집 — 본문 텍스트에서 표 셀 내용은 제외해 중복 방지
            # (표 내용은 result["tables"]로 별도 제공되므로 text + tables 합이 전체 커버리지)
            table_roots = _findall_local(tree, "tbl")
            in_table = set()
            for tbl in table_roots:
                for el in tbl.iter():
                    in_table.add(id(el))

            # 텍스트 추출 (hp:t 태그 — 네임스페이스 무관, 표 내부 hp:t 제외)
            texts = [
                el.text for el in _findall_local(tree, "t")
                if el.text and id(el) not in in_table
            ]
            sec_text = "\n".join(texts)
            result["sections"].append({"name": s_file, "text": sec_text})
            full_text_chunks.append(sec_text)

            # 표 추출 (hp:tbl 태그 — 네임스페이스 무관)
            for tbl in table_roots:
                rows = []
                for tr in [t for t in tbl.iter() if _local_name(t.tag) == "tr"]:
                    row_cells = []
                    for tc in [c for c in tr.iter() if _local_name(c.tag) == "tc"]:
                        cell_texts = [t.text for t in tc.iter() if _local_name(t.tag) == "t" and t.text]
                        row_cells.append(" ".join(cell_texts).strip())
                    if row_cells:
                        rows.append(row_cells)
                if rows:
                    result["tables"].append(rows)

        result["text"] = "\n\n".join(full_text_chunks)

    return result


def parse_hwp_legacy(file_path: str) -> dict:
    """구형 HWP (v5.0) 파서 (hwp-hwpx-parser 우선, olefile raw 스트림 fallback).

    hwp-hwpx-parser가 ImportError가 아니라 개별 파일에서 실패해도 OLE 폴백을
    시도하고, 둘 다 실패하면 두 오류를 합쳐 반환한다.
    """
    primary_error = None
    # 우선: hwp-hwpx-parser (PyPI, 순수 파이썬 — HWP5Reader API)
    try:
        from hwp_hwpx_parser import HWP5Reader
        reader = HWP5Reader(file_path)
        text = reader.extract_text() or ""
        tables = []
        try:
            for tbl in reader.get_tables():
                rows = getattr(tbl, "rows", None) or []
                if rows:
                    tables.append([[str(c) for c in row] for row in rows])
        except Exception:
            pass
        reader.close()
        return {
            "file_path": file_path,
            "format": "HWP 5.0 (Binary)",
            "text": text,
            "tables": tables,
            "metadata": {},
        }
    except ImportError:
        pass  # 패키지 미설치 — olefile fallback으로 진행
    except Exception as e:
        primary_error = f"hwp-hwpx-parser failed: {str(e)}"

    # Fallback: olefile 사용 (hwp-hwpx-parser 미설치 또는 실패 시 원시 스트림 디컴프레션)
    try:
        import olefile
        import zlib
        ole = olefile.OleFileIO(file_path)
        streams = ole.listdir()
        body_streams = [s for s in streams if s[0] == "BodyText"]
        text_chunks = []
        for b in body_streams:
            stream_data = ole.openstream(b).read()
            try:
                decompressed = zlib.decompress(stream_data, -15)
                text = decompressed.decode('utf-16-le', errors='ignore')
                clean = "".join([c for c in text if c.isprintable() or c in "\n\r\t"])
                text_chunks.append(clean)
            except Exception:
                pass
        ole.close()
        if not text_chunks and primary_error:
            return {
                "file_path": file_path,
                "format": "HWP 5.0",
                "error": f"{primary_error}; OLE fallback produced no readable text",
            }
        return {
            "file_path": file_path,
            "format": "HWP 5.0 (OLE Fallback)",
            "text": "\n".join(text_chunks),
            "metadata": {
                "note": "Extracted via raw OLE stream decompression",
                "quality": "rough — 레코드 구조를 해석하지 않는 휴리스틱 추출이므로 깨진 문자가 남을 수 있고 표/개요 등 구조는 유실됨. 정확한 추출이 필요하면 pip install hwp-hwpx-parser",
            },
        }
    except Exception as e:
        prefix = f"{primary_error}; " if primary_error else ""
        return {
            "file_path": file_path,
            "format": "HWP 5.0",
            "error": f"{prefix}Failed to parse HWP via OLE fallback: {str(e)} (install hwp-hwpx-parser or olefile)"
        }


def parse_pdf(file_path: str) -> dict:
    """PDF 텍스트 및 표 추출 (PyMuPDF 우선, 실패시 pypdf fallback).

    ImportError뿐 아니라 실행 중 예외(손상 파일 등)가 나도 pypdf 폴백을
    시도하고, 둘 다 실패하면 두 오류 사슬을 함께 반환한다.
    """
    result = {
        "file_path": file_path,
        "format": "PDF",
        "sections": [],
        "text": "",
        "tables": [],
        "metadata": {}
    }
    errors = []
    # Try PyMuPDF
    try:
        import fitz
        doc = fitz.open(file_path)
        result["metadata"] = {k: str(v) for k, v in (doc.metadata or {}).items() if v}
        result["metadata"]["page_count"] = str(len(doc))
        chunks = []
        for i, page in enumerate(doc):
            t = page.get_text("text") or ""
            chunks.append(t)
            result["sections"].append({"name": f"page_{i+1}", "text": t})
        result["text"] = "\n\n".join(chunks)
        doc.close()
        return result
    except ImportError:
        errors.append("pymupdf not installed")
    except Exception as e:
        errors.append(f"PyMuPDF failed: {e}")

    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        result["metadata"]["page_count"] = str(len(reader.pages))
        if reader.metadata:
            for k, v in reader.metadata.items():
                result["metadata"][k] = str(v) if v else ""
        chunks = []
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
            except Exception:
                t = ""
            chunks.append(t)
            result["sections"].append({"name": f"page_{i+1}", "text": t})
        result["text"] = "\n\n".join(chunks)
        return result
    except ImportError:
        errors.append("pypdf not installed")
    except Exception as e:
        errors.append(f"pypdf failed: {e}")

    return {
        "file_path": file_path,
        "format": "PDF",
        "error": "; ".join(errors) + ". Install pymupdf (pip install pymupdf) or pypdf (pip install pypdf)."
    }


def mineru_available() -> tuple[bool, str]:
    """MinerU BYOB 게이트 — 바이너리/패키지와 GPU(또는 명시적 CPU 허용)를 확인.

    MinerU/Popo는 4B급 모델 파이프라인이라 CPU 추론은 사실상 비실용적이다.
    MINERU_ALLOW_CPU=1로 명시 허용한 경우에만 CPU 경로를 통과시킨다.
    반환: (사용 가능 여부, 사유 문자열)
    """
    import importlib.util
    import shutil
    has_bin = shutil.which("mineru") is not None
    has_pkg = importlib.util.find_spec("magic_pdf") is not None
    if not (has_bin or has_pkg):
        return False, "mineru 바이너리/magic_pdf 패키지 없음 (pip install -U 'mineru[core]')"
    if os.environ.get("MINERU_ALLOW_CPU") == "1":
        return True, "cpu-allowed"
    try:
        import torch
        if torch.cuda.is_available():
            return True, "cuda"
        return False, "GPU 없음 — MINERU_ALLOW_CPU=1로 CPU 강행 가능 (느림)"
    except ImportError:
        # torch 미설치 — 바이너리 경로는 자체 런타임을 쓸 수 있으므로 통과
        return (True, "binary") if has_bin else (False, "torch 미설치 — GPU 확인 불가")


def parse_pdf_mineru(file_path: str) -> dict:
    """MinerU(BYOB)로 스캔본/복합 레이아웃 PDF를 마크다운으로 변환해 흡수한다.

    기본 파서가 텍스트 레이어를 읽는 것과 달리 레이아웃·표 경계를 복원한다.
    결과가 원본 이미지 기반 추론물이므로 원본 대조 주석을 metadata에 남긴다.
    """
    import subprocess
    import tempfile
    ok, reason = mineru_available()
    if not ok:
        return {"file_path": file_path, "format": "PDF",
                "error": f"MinerU 사용 불가: {reason}"}
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            ["mineru", "-p", file_path, "-o", tmp],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
        if proc.returncode != 0:
            return {"file_path": file_path, "format": "PDF",
                    "error": f"mineru failed: {proc.stderr.strip()[:300]}"}
        mds = sorted(Path(tmp).rglob("*.md"))
        if not mds:
            return {"file_path": file_path, "format": "PDF",
                    "error": "mineru produced no markdown output"}
        text = "\n\n".join(m.read_text(encoding="utf-8") for m in mds)
    return {
        "file_path": file_path,
        "format": "PDF (MinerU)",
        "sections": [],
        "text": text,
        "tables": [],
        "metadata": {
            "engine": "mineru",
            "note": "MinerU 레이아웃 추론 결과 — 수치·표 경계는 원본 스캔 대조 필수",
        },
    }


def parse_anydoc(file_path: str) -> dict:
    """Parse office documents, spreadsheets, presentations, and ebooks via Firecrawl AnyDoc."""
    ext = os.path.splitext(file_path)[1].lower()
    fmt_name = ext[1:].upper()
    if ext == ".csv":
        try:
            import csv
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                rows = [row for row in csv.reader(f) if any(cell.strip() for cell in row)]
            text_lines = ["\t".join(row) for row in rows]
            text = "\n".join(text_lines)
            return {
                "file_path": file_path,
                "format": "CSV",
                "metadata": {"engine": "python-csv"},
                "sections": [{"name": "body", "text": text}],
                "tables": [rows] if rows else [],
                "text": text,
            }
        except Exception:
            pass

    try:
        import anydoc
        text = anydoc.to_markdown(file_path)
        return {
            "file_path": file_path,
            "format": fmt_name,
            "metadata": {"engine": "firecrawl-anydoc"},
            "sections": [{"name": "body", "text": text}],
            "tables": [],
            "text": text,
        }
    except ImportError:
        import subprocess
        try:
            res = subprocess.run(
                ["npx", "-y", "@firecrawl/anydoc", file_path],
                capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                shell=sys.platform == "win32",
                timeout=30,
            )
            if res.returncode == 0:
                text = res.stdout
                return {
                    "file_path": file_path,
                    "format": fmt_name,
                    "metadata": {"engine": "npx @firecrawl/anydoc"},
                    "sections": [{"name": "body", "text": text}],
                    "tables": [],
                    "text": text,
                }
            return {
                "file_path": file_path,
                "format": fmt_name,
                "error": f"anydoc CLI failed (exit {res.returncode}): {res.stderr.strip()}",
            }
        except Exception as e:
            return {
                "file_path": file_path,
                "format": fmt_name,
                "error": f"anydoc not available: {e}. Install via 'pip install firecrawl-anydoc'",
            }
    except Exception as e:
        return {
            "file_path": file_path,
            "format": fmt_name,
            "error": f"Failed to convert with anydoc: {e}",
        }


ANYDOC_EXTENSIONS = {
    ".doc", ".docx", ".docm", ".dot", ".dotx",
    ".ppt", ".pptx", ".pps", ".ppsx", ".pot", ".potx", ".odp",
    ".xls", ".xlsx", ".xlsm", ".xlsb", ".ods", ".csv",
    ".odt", ".rtf", ".epub",
}


def _result_quality(data: dict) -> str:
    """결과 품질 판정: metadata.quality 또는 최상위 quality가 rough면 rough."""
    q = str(data.get("quality", "") or data.get("metadata", {}).get("quality", ""))
    return "rough" if q.startswith("rough") else "clean"


def _ensure_quality(data: dict) -> dict:
    """다운스트림용으로 결과 JSON에 quality 필드가 항상 있도록 보장."""
    q = _result_quality(data)
    data.setdefault("quality", q)
    if isinstance(data.get("metadata"), dict):
        data["metadata"].setdefault("quality", q)
    return data


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="한국 공문서 및 오피스 문서(HWP/HWPX/PDF/DOCX/XLSX/PPTX) 고속 파싱 도구")
    parser.add_argument("input_file", help="입력 파일 (.hwp, .hwpx, .pdf, .docx, .xlsx, .pptx, .csv 등)")
    parser.add_argument("--output", "-o", help="결과 JSON 저장 경로 (미지정시 stdout 출력)")
    parser.add_argument("--markdown", "-m", action="store_true", help="결과를 마크다운 형식으로 출력")
    parser.add_argument("--strict", action="store_true",
                        help="HWP OLE 휴리스틱 추출(quality=rough)을 오류(exit 2)로 거부 (기본은 경고 유지)")
    parser.add_argument("--engine", choices=["auto", "mineru"], default="auto",
                        help="PDF 엔진 선택. mineru=스캔본·다단 표 복원 (BYOB, GPU 권장. "
                             "MINERU_ALLOW_CPU=1로 CPU 강행)")

    args = parser.parse_args()
    file_path = os.path.abspath(args.input_file)

    if not os.path.exists(file_path):
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".hwpx":
        data = parse_hwpx(file_path)
    elif ext == ".hwp":
        data = parse_hwp_legacy(file_path)
    elif ext == ".pdf":
        data = parse_pdf_mineru(file_path) if args.engine == "mineru" else parse_pdf(file_path)
        if "error" in data:
            print(f"Error: {data['error']}", file=sys.stderr)
            sys.exit(1)
    elif ext in ANYDOC_EXTENSIONS:
        data = parse_anydoc(file_path)
        if "error" in data:
            print(f"Error: {data['error']}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Unsupported file extension: {ext} (supported: .hwpx, .hwp, .pdf, .docx, .xlsx, .pptx, .csv, .rtf, .odt, .odp, .epub)", file=sys.stderr)
        sys.exit(1)

    if "error" in data:
        print(f"Error: {data['error']}", file=sys.stderr)
        sys.exit(1)

    _ensure_quality(data)
    if _result_quality(data) == "rough":
        if args.strict:
            print("Error: HWP rough 추출 품질 — --strict 모드에서 거부합니다 (exit 2)", file=sys.stderr)
            sys.exit(2)
        print("[WARN] HWP rough 추출 품질 — 휴리스틱 결과이므로 원본 대조 요망", file=sys.stderr)

    if args.markdown:
        md_output = f"# Document Content: {os.path.basename(file_path)}\n\n"
        md_output += f"- **Format:** {data.get('format')}\n"
        if data.get("metadata"):
            md_output += f"- **Metadata:** {json.dumps(data.get('metadata'), ensure_ascii=False)}\n\n"
        md_output += "## Text Body\n\n"
        md_output += data.get("text", "") + "\n\n"
        if data.get("tables"):
            md_output += "## Extracted Tables\n\n"
            for i, tbl in enumerate(data["tables"]):
                md_output += f"### Table {i+1}\n"
                if not tbl:
                    continue
                # Determine column count
                col_count = max(len(r) for r in tbl)
                # Header row (first row as header)
                header = [_escape_md_cell(c) for c in tbl[0]]
                # Pad header if needed
                while len(header) < col_count:
                    header.append("")
                md_output += "| " + " | ".join(header) + " |\n"
                md_output += "| " + " | ".join(["---"] * col_count) + " |\n"
                for row in tbl[1:]:
                    cells = [_escape_md_cell(c) for c in row]
                    while len(cells) < col_count:
                        cells.append("")
                    md_output += "| " + " | ".join(cells) + " |\n"
                # Single-row table (no header separator duplication needed beyond above)
                if len(tbl) == 1:
                    pass
                md_output += "\n"
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(md_output)
            print(f"Saved markdown to: {args.output}")
        else:
            print(md_output)
    else:
        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"Saved JSON to: {args.output}")
        else:
            print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
