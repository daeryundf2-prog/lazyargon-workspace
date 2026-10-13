#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
stamp_evidence.py - 대법원 전자소송(ECFS) 규격 서증(갑/을 제O호증) 표찰 및 Bates 번호 스탬핑 도구
"""

import os
import sys
import re
import argparse


def _get_korean_font():
    """Try to locate a Korean-capable font file; return its path or None."""
    for candidate in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "NotoSansKR-Regular.ttf"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "NotoSansKR-Regular.otf"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]:
        if os.path.exists(candidate):
            return candidate
    return None


def _label_box_width(label: str, fontsize: float = 11.0, min_width: float = 110.0) -> float:
    """라벨이 박스 안에 들어가도록 폭을 추정한다.

    한글/CJK 글리프는 대략 1em, 라틴/숫자/공백은 0.55em로 계산하고 좌우 여유를
    더한다. 기존 고정 110pt에서는 '을 제10호증의 3' 같은 긴 라벨이
    insert_textbox에서 rc<0으로 조용히 누락될 수 있었다.
    """
    em = sum(1.0 if ord(ch) > 0x2E7F else 0.55 for ch in label)
    return max(min_width, em * fontsize + 18.0)


def format_evidence_label(label: str, branch: int | None = None) -> str:
    """서증 부호와 가지번호를 표준 대법원 전자소송 형식(예: '갑 제1호증의 2')으로 포맷팅."""
    label = label.strip()
    if branch is not None and branch > 0:
        # 이미 '의 O'가 붙어있는지 확인
        if not re.search(r"의\s*\d+$", label):
            label = f"{label}의 {branch}"
    return label


def _occupied_rects(page):
    """페이지의 기존 위젯(폼 필드)·주석의 점유 영역을 반환한다 (PyMuPDF page)."""
    rects = []
    try:
        widgets = page.widgets()
        if widgets:
            for w in widgets:
                rects.append(w.rect)
    except Exception:
        pass
    try:
        annots = page.annots()
        if annots:
            for a in annots:
                rects.append(a.rect)
    except Exception:
        pass
    return rects


def _free_stamp_y(page, x1: float, x2: float, y1: float, box_height: float, page_height: float, max_shifts: int = 8):
    """표찰 박스가 기존 위젯/주석과 겹치지 않는 y1을 찾아 아래로 이동한다.

    여백을 손상시키지 않고 표찰을 오버레이하기 위해, 겹침 발견 시 박스 높이
    만큼씩 아래로 내린다. 최대 max_shifts 회까지 — 그래도 겹치면 마지막
    위치를 반환하고 호출부에서 경고를 남긴다.
    """
    import fitz

    occupied = _occupied_rects(page)
    y0 = y1
    for _ in range(max_shifts + 1):
        candidate = fitz.Rect(x1, y1, x2, y1 + box_height)
        if not any(candidate.intersects(r) for r in occupied):
            return y1, y1 != y0
        y1 += box_height + 6
        if y1 + box_height > page_height * 0.35:
            break
    return y1, True


def stamp_pdf_pymupdf(input_pdf: str, output_pdf: str, label: str, bates_prefix: str = "P", start_page: int = 1, all_pages: bool = True, right_margin: float = 25.0, allow_broken_font: bool = False):
    """PyMuPDF(fitz)를 활용한 고품질 서증 라벨 및 Bates 번호 인자"""
    from dep_help import require
    require("fitz")  # 미설치 시 설치 안내 + exit 3 — except로 삼키지 않는다
    import fitz  # PyMuPDF

    # Ensure output directory exists
    out_dir = os.path.dirname(os.path.abspath(output_pdf))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    try:
        doc = fitz.open(input_pdf)
    except Exception as e:
        print(f"[!] Failed to open PDF: {e}", file=sys.stderr)
        return False

    if doc.is_encrypted:
        print("[!] Encrypted PDF requires password — cannot stamp", file=sys.stderr)
        doc.close()
        return False

    total_pages = len(doc)
    if total_pages == 0:
        print("[!] PDF has no pages", file=sys.stderr)
        doc.close()
        return False

    print(f"[*] Processing {total_pages} pages in '{input_pdf}'...")

    korean_font_path = _get_korean_font()
    if korean_font_path:
        print(f"[*] Using Korean font: {korean_font_path}")
    else:
        print("[WARN] No Korean font found — Hangul in label may render as boxes. Place NotoSansKR-Regular.ttf next to script.", file=sys.stderr)
        if not allow_broken_font:
            print("[!] Refusing to stamp without a Korean font (Hangul would break). Install a font (macOS AppleSDGothicNeo / Windows malgun / Linux NanumGothic) or re-run with --allow-broken-font to explicitly opt in to broken output.", file=sys.stderr)
            doc.close()
            return False

    for idx, page in enumerate(doc):
        current_page_num = start_page + idx
        rect = page.rect

        # 1. 서증 표찰 — 기본 전 페이지, --first-only 지정 시 첫 페이지만
        should_stamp = all_pages or idx == 0
        if should_stamp:
            box_height = 24
            box_width = _label_box_width(label)
            box_x1 = max(5.0, rect.width - right_margin - box_width)
            box_x2 = min(rect.width - 5.0, rect.width - right_margin)
            box_y1 = 20
            box_y1, overlapped = _free_stamp_y(page, box_x1, box_x2, box_y1, box_height, rect.height)
            if overlapped:
                print(f"[WARN] Page {idx + 1}: stamp area overlaps existing widget/annot — box pushed down to y={box_y1:.0f}", file=sys.stderr)
            box_y2 = box_y1 + box_height

            page.draw_rect(fitz.Rect(box_x1, box_y1, box_x2, box_y2), color=(0.8, 0, 0), width=1.5, fill=(1, 1, 1))

            text_rect = fitz.Rect(box_x1, box_y1 + 4, box_x2, box_y2)
            # 주의: fontfile만 지정하면 PyMuPDF가 이를 무시하고 helv로 렌더링해
            # 한글이 '?'로 깨진다. 반드시 fontname을 함께 지정해 파일 폰트를 등록해야 함.
            inserted = False
            if korean_font_path:
                try:
                    rc = page.insert_textbox(
                        text_rect,
                        label,
                        fontsize=11,
                        fontname="KOR",
                        fontfile=korean_font_path,
                        color=(0.8, 0, 0),
                        align=fitz.TEXT_ALIGN_CENTER,
                    )
                    inserted = rc >= 0
                except Exception:
                    inserted = False
            if not inserted:
                print("[WARN] Korean font insert failed — falling back to helv (Hangul will break).", file=sys.stderr)
                rc_fallback = page.insert_textbox(
                    text_rect, label, fontsize=11, fontname="helv", color=(0.8, 0, 0), align=fitz.TEXT_ALIGN_CENTER
                )
                if rc_fallback < 0:
                    print(f"[WARN] Label '{label}' did not fit even in fallback box — label skipped (rc={rc_fallback:.2f})", file=sys.stderr)

        # 2. Bates 일련번호 — 단일 번호 (예: P-0001)
        # 주의: insert_textbox는 공간이 부족하면 예외 대신 음수를 반환하고 텍스트를
        # 조용히 누락하므로, 충분한 높이를 확보하고 반환값을 반드시 검사한다.
        bates_text = f"{bates_prefix}-{current_page_num:04d}"
        bates_rect = fitz.Rect(rect.width / 2 - 120, rect.height - 34, rect.width / 2 + 120, rect.height - 6)
        rc = page.insert_textbox(
            bates_rect,
            bates_text,
            fontsize=9,
            fontname="helv",
            color=(0.2, 0.2, 0.2),
            align=fitz.TEXT_ALIGN_CENTER,
        )
        if rc < 0:
            print(f"[WARN] Bates number '{bates_text}' did not fit and was skipped (rc={rc:.2f})", file=sys.stderr)

    try:
        doc.save(output_pdf, garbage=4, deflate=True)
    except Exception as e:
        print(f"[!] Failed to save PDF: {e}", file=sys.stderr)
        doc.close()
        return False
    doc.close()
    print(f"[OK] Successfully generated court-stamped PDF: {output_pdf} ({total_pages} pages, Bates {bates_prefix}-{start_page:04d}~{bates_prefix}-{start_page+total_pages-1:04d})")
    return True


def main():
    parser = argparse.ArgumentParser(description="대법원 전자소송 서증 표찰(갑/을 제O호증) 및 Bates 번호 스탬퍼")
    parser.add_argument("input_pdf", help="원본 PDF 파일 경로")
    parser.add_argument("--output", "-o", required=True, help="스탬핑 완료된 출력 PDF 경로")
    parser.add_argument("--label", "-l", required=True, help="서증 부호 및 번호 (예: '갑 제1호증', '을 제2호증의 1')")
    parser.add_argument("--branch", "-b", type=int, default=None, help="가지번호 (예: 1 지정 시 '갑 제1호증의 1')")
    parser.add_argument("--prefix", "-p", default="P", help="Bates 페이지 접두사 (기본: 'P')")
    parser.add_argument("--start", "-s", type=int, default=1, help="시작 페이지 번호 (기본: 1)")
    parser.add_argument("--first-only", action="store_true", help="첫 페이지만 표찰 (미지정 시 전 페이지 표찰)")
    parser.add_argument("--margin", type=float, default=25.0, help="표찰 박스의 우측 여백(pt, 기본: 25) — 인장·전송표와 겹칠 때 조정")
    parser.add_argument("--allow-broken-font", action="store_true", help="한글 폰트 없이도 강제 스탬핑 (라벨 깨짐 감수, 법원 제출용에는 사용 금지)")

    args = parser.parse_args()

    if not os.path.exists(args.input_pdf):
        print(f"Error: Input file not found: {args.input_pdf}", file=sys.stderr)
        sys.exit(1)

    all_pages = not args.first_only
    final_label = format_evidence_label(args.label, args.branch)

    success = stamp_pdf_pymupdf(
        input_pdf=args.input_pdf,
        output_pdf=args.output,
        label=final_label,
        bates_prefix=args.prefix,
        start_page=args.start,
        all_pages=all_pages,
        right_margin=args.margin,
        allow_broken_font=args.allow_broken_font,
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
