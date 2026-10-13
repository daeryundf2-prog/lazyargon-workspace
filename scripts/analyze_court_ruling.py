#!/usr/bin/env python3
"""analyze_court_ruling.py - 판결문 구조 분석기 (섹션 분할·인용 추출·쟁점표 골격).

판결문 전문(korean-doc-parser의 텍스트 출력)에서 【주 문】·【이 유】 등 주요
섹션을 분할하고, 인용 법령(조문)·인용 판례(선고 형식)를 결정적으로 추출하며,
쟁점 요약표 골격을 만든다. "요약" 자체는 에이전트의 몫 — 이 도구는 구조와
근거 목록을 정확하게 제공한다.

탐지 규칙:
    주요 섹션  【주 문】·【이 유】·【사 실】·【증 거】 (괄호 유무·공백 무관)
    하위 구간  "…의 주장 / …의 항변 / …에 대한 판단" 형태의 번호 매기기 행
    법령 인용  「…법 제N조(의M)」 형태 전수
    판례 인용  대법원 YYYY. M. D. 선고 … 판결 형태 전수

Exit code: 0 완료 / 2 실행 오류
CLI:
    python scripts/analyze_court_ruling.py 판결문.txt -o 분석.md
    python scripts/analyze_court_ruling.py 판결문.txt --json -o 구조.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

try:
    from verify_legal_factuality import verify_legal_text
except ImportError:
    try:
        from scripts.verify_legal_factuality import verify_legal_text
    except ImportError:
        verify_legal_text = None

# 주요 섹션 헤더: 【주 문】 / 주 문 / (주 문) 등 짧은 단독 행
_PRIMARY_RE = re.compile(r"^\s*[【(\[]?\s*(주\s*문|이\s*유|사\s*실|증\s*거|판\s*단|결\s*론)\s*[】)\]]?\s*$")
# 하위 구간: "1. 원고의 주장" / "2. 피고들의 항변에 대하여" / "가. 위 …에 대한 판단"
_SUBSECTION_RE = re.compile(
    r"^\s*(?:[0-9]+\.|[가-힣][.])\s*(?P<name>[^(\n]{2,40}?(?:주장|항변|판단|판단한다))\s*$"
)
# {1,10}: '민법'·'형법'처럼 법 앞 글자가 한 글자인 법률명도 잡는다
_LAW_RE = re.compile(
    r"[가-힣]{1,10}법(?:률)?\s*제\s*\d+\s*조(?:\s*의\s*\d+)?"
)
_PRECEDENT_RE = re.compile(
    r"(?:대법원|헌법재판소)\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*선고[^,，。\n]{0,40}?(?:판결|결정)"
)


def split_sections(text: str) -> list[dict]:
    """헤더 행 기준으로 섹션을 분할한다. 헤더가 전혀 없으면 전체 1개 섹션."""
    lines = text.splitlines()
    marks: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _PRIMARY_RE.match(line)
        if m:
            name = re.sub(r"\s+", "", m.group(1))
            marks.append((i, name))
    if not marks:
        return [{"name": "전문", "start": 0, "end": len(lines), "chars": len(text)}]

    sections: list[dict] = []
    for idx, (start, name) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        body = "\n".join(lines[start + 1:end]).strip()
        sections.append({"name": name, "start": start + 1, "end": end, "chars": len(body)})
    return sections


def find_subsections(text: str) -> list[str]:
    """주장·항변·판단 하위 구간 이름을 출현 순서대로 중복 없이 반환."""
    names: list[str] = []
    for line in text.splitlines():
        m = _SUBSECTION_RE.match(line)
        if m:
            name = m.group("name").strip()
            if name not in names:
                names.append(name)
    return names


def extract_laws(text: str) -> list[str]:
    """인용 법령 조문을 출현 순서대로 중복 없이 반환.

    '민법 제 388조'와 '민법 제388조'는 공백 정규화 후 같은 조문으로 본다
    (dedupe 키는 무공간 형태, 표시는 첫 출현 형태).
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in _LAW_RE.finditer(text):
        display = re.sub(r"\s+", " ", m.group(0))
        key = display.replace(" ", "")
        if key not in seen:
            seen.add(key)
            out.append(display)
    return out


def extract_precedents(text: str) -> list[str]:
    """인용 판례(선고 형식)를 출현 순서대로 중복 없이 반환."""
    out: list[str] = []
    for m in _PRECEDENT_RE.finditer(text):
        prec = re.sub(r"\s+", " ", m.group(0))
        if prec not in out:
            out.append(prec)
    return out


ISSUE_TABLE_SKELETON = """| 쟁점 | 원고 주장 | 피고 주장 | 법원 판단 |
| :-- | :-- | :-- | :-- |
| {쟁점1} | {요지} | {요지} | {요지} |
| {쟁점2} | {요지} | {요지} | {요지} |"""


def render_markdown(
    sections: list[dict],
    subsections: list[str],
    laws: list[str],
    precedents: list[str],
    audit: dict | None = None,
) -> str:
    lines = ["# 판결문 구조 분석\n"]

    lines.append("## 섹션 구조\n")
    lines.append("| 섹션 | 시작 줄 | 글자 수 |")
    lines.append("| :-- | ---: | ---: |")
    for s in sections:
        lines.append(f"| {s['name']} | {s['start']} | {s['chars']:,} |")

    if subsections:
        lines.append("\n## 주장·항변·판단 구간\n")
        for name in subsections:
            lines.append(f"- {name}")

    lines.append("\n## 인용 법령\n")
    if laws:
        for law in laws:
            lines.append(f"- {law}")
    else:
        lines.append("- (조문 인용을 발견하지 못했다)")

    lines.append("\n## 인용 판례\n")
    if precedents:
        for prec in precedents:
            lines.append(f"- {prec}")
    else:
        lines.append("- (선고 형식의 판례 인용을 발견하지 못했다)")

    if audit:
        lines.append("\n## 인용 법령·판례 무결성 검증 (Factuality Audit)\n")
        lines.append(f"- **검증 결과:** `{audit['verdict']}`")
        if audit.get("errors"):
            lines.append(f"- **오류 ({len(audit['errors'])}건):**")
            for err in audit["errors"]:
                lines.append(f"  - ❌ {err}")
        if audit.get("warnings"):
            lines.append(f"- **주의 ({len(audit['warnings'])}건):**")
            for warn in audit["warnings"]:
                lines.append(f"  - ⚠️ {warn}")
        if not audit.get("errors") and not audit.get("warnings"):
            lines.append(f"- ✅ 모든 인용 법령 및 판례의 형식과 경계가 검증되었습니다.")

    lines.append("\n## 쟁점 요약표 (골격 — 에이전트·사람이 채운다)\n")
    lines.append(ISSUE_TABLE_SKELETON)
    lines.append("\n> 위 표의 판단 요지는 원문에서 인용해 채우고, 의역이 필요하면 윤문은 humanize-korean으로 하되 법률 용어는 유지하십시오.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="판결문 구조 분석기 (섹션·법령·판례·쟁점표 골격)")
    p.add_argument("input", help="판결문 텍스트 파일 (parse_korean_doc 출력 권장)")
    p.add_argument("--output", "-o", default="", help="출력 경로 (미지정 시 stdout)")
    p.add_argument("--json", action="store_true", help="JSON으로 출력 (섹션 원문 포함 — 에이전트 요약용)")
    p.add_argument("--verify", action="store_true", help="인용 법령 및 판례에 대한 사실성 및 경계값 검증 수행")
    p.add_argument("--source", help="Optional reference source file for grounding verification")
    p.add_argument("--morph-grounding", action="store_true", help="Kiwi morphological grounding check against source")
    p.add_argument("--high-fidelity", action="store_true", help="Local High-Fidelity gate: require --source and <evidence> tags plus morpheme overlap (no Vertex API)")
    p.add_argument("--strict", action="store_true", help="사실성 검증 실패 시 에러 종료")
    args = p.parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"error: 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        return 2
    with open(args.input, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    if not text.strip():
        print("error: 입력이 비어 있습니다 (스캔본이면 OCR이 필요합니다)", file=sys.stderr)
        return 2

    source_text = None
    if args.source and os.path.isfile(args.source):
        with open(args.source, "r", encoding="utf-8", errors="replace") as sf:
            source_text = sf.read()

    sections = split_sections(text)
    subsections = find_subsections(text)
    laws = extract_laws(text)
    precedents = extract_precedents(text)

    audit = None
    if (args.verify or args.high_fidelity or args.morph_grounding) and verify_legal_text is not None:
        audit = verify_legal_text(
            text,
            source_text=source_text,
            morph_grounding=args.morph_grounding,
            high_fidelity=args.high_fidelity,
        )
        if (args.strict or args.high_fidelity) and audit.get("errors"):
            print(f"[FAIL] 판결문 인용 사실성 검증 실패 ({len(audit['errors'])}건 오류):", file=sys.stderr)
            for err in audit["errors"]:
                print(f"  - {err}", file=sys.stderr)
            return 1

    if args.json:
        lines = text.splitlines()
        body = {
            "sections": [
                {
                    "name": s["name"], "start": s["start"], "end": s["end"],
                    "chars": s["chars"],
                    "text": "\n".join(lines[s["start"]:s["end"]]).strip(),
                }
                for s in sections
            ],
            "subsections": subsections,
            "laws": laws,
            "precedents": precedents,
        }
        if audit is not None:
            body["factuality_audit"] = audit
        out_text = json.dumps(body, ensure_ascii=False, indent=2)
    else:
        out_text = render_markdown(sections, subsections, laws, precedents, audit=audit)

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_text)
        print(f"[OK] 분석 결과 저장: {args.output}")
    else:
        print(out_text)
    return 0


# ── 콘솔 하드닝 (#84) ───────────────────────────────────────────────
import os as _os  # noqa: E402
import sys as _sys  # noqa: E402

_sys.path.insert(0, _os.path.dirname(_os.path.abspath(__file__)))
import console as _console  # noqa: E402

if __name__ == "__main__":
    _console.force_utf8_console()
    raise SystemExit(main())
