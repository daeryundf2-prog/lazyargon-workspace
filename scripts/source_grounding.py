#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_grounding.py — 보고서 문장을 원본 자료(카톡·녹취·OCR 텍스트·첨부 파일)와 1:1 대조한다.

verify_report.py 의 해시·금지어 검사로는 잡히지 않는 환각을 결정적으로 차단한다 (LLM 0콜):
  1. 인용 실재: "…", “…”, 「…」, 『…』, <evidence>…</evidence> 안의 문장이 원본 텍스트에 그대로 있어야 한다.
  2. 화자 귀속: 인용 줄에 화자가 한 명 언급되면 원본 발언자와 같아야 한다. 두 명 이상이면 그중 누구도
     발언자가 아닐 때, 또는 조사(은/는/이/가/께서/의/에게서/한테서/로부터, '이름 :')로 드러난 말한 사람이
     원본 발언자가 아닐 때 오류다.
  3. 시각 실재: 보고서의 "날짜 시:분" 시각이 원본/타임라인에 있어야 한다.
  4. 건수 실재: "N건/개/회/통/명" 수치가 원본(또는 분석 산출물)에 있어야 한다.
  5. 첨부 실재: 보고서가 언급한 증거 파일명(.jpg .m4a .pdf .hwp …)이 자료 폴더에 실제로 있어야 한다.
코드블록은 검사하지 않는다. '미확인/미측정/[INSUFFICIENT_DATA]'가 있는 줄도 같은 검사를 하되, 원본에 없는
인용·시각·수치·파일은 오류 대신 경고로 보고한다(정직한 유보). 원본에 있는 인용의 화자를 틀리게 적으면 그 줄에서도 오류다.
원본이 이미지·음성·PDF뿐이면 텍스트 대조가 불가능하므로, OCR/STT 텍스트를 자료 폴더에 함께 두어야 한다.

CLI: python scripts/source_grounding.py 보고서.md --sources 자료폴더 [파일...] [--timeline events.json] [--json]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

try:
    from report_core import extract_timestamps
except ImportError:
    from scripts.report_core import extract_timestamps

TEXT_EXTS = {".txt", ".csv", ".tsv", ".json", ".jsonl", ".md", ".log", ".srt", ".vtt", ".html", ".htm", ".xml"}
EVIDENCE_FILE_EXTS = (
    "jpg|jpeg|png|gif|heic|webp|bmp|tif|tiff|mp4|mov|avi|mkv|m4a|mp3|wav|aac|amr|3gp|ogg|"
    "pdf|hwp|hwpx|doc|docx|xls|xlsx|ppt|pptx|zip|7z|e01|ex01|dd|raw|img|vmdk|pst|eml|msg|db|sqlite|txt|csv"
)
FILE_TOKEN_RE = re.compile(rf"(?<![\w./\\-])([\w가-힣()\[\] .,_-]*?[\w가-힣)\]_-]\.(?:{EVIDENCE_FILE_EXTS}))(?![\w])", re.IGNORECASE)
QUOTE_RES = [
    re.compile(r'"([^"\n]{2,300})"'),
    re.compile(r"“([^”\n]{2,300})”"),
    re.compile(r"「([^」\n]{2,300})」"),
    re.compile(r"『([^』\n]{2,300})』"),
]
EVIDENCE_TAG_RE = re.compile(r"<evidence(?:\s[^>]*)?>(.*?)</evidence>", re.IGNORECASE | re.DOTALL)
COUNT_RE = re.compile(
    r"(?<![A-Za-z\d.,제])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"(%|건|개(?![월년])|회(?![사의원신차])|통(?![화장신보])|명(?![의령시확백])|KB|MB|GB|TB|바이트|페이지|프레임)(?![가-힣]*호증)"
)
TAG_RE = re.compile(r"<(?!/?evidence\b)[a-zA-Z/][^>]*>", re.IGNORECASE)
SPEAKER_LINE_RE = re.compile(r"(?:^|[,\]\)]\s*)([가-힣A-Za-z][가-힣A-Za-z0-9 ]{0,14}?)\s*:\s*(.+)$")
ABSTAIN_RE = re.compile(r"미확인|미측정|INSUFFICIENT_DATA|UNVERIFIED|판단\s*불능")
MIN_QUOTE_CHARS = 4
SPEAKER_MARK = r"\s*(?:께서|에게서|한테서|로부터|은|는|이|가|의)(?![가-힣])|\s*:"


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", html.unescape(s))
    s = re.sub(r"[‘’'`]", "'", s)
    s = re.sub(r"[“”\"]", '"', s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().strip(" .,!?…~").strip()


def _strip_code(text: str) -> str:
    text = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    return re.sub(r"`[^`\n]*`", "", text)


def _read_text(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm", ".xml"}:
        raw = re.sub(r"<[^>]+>", " ", raw)
    return raw


def collect_sources(paths: list[str]) -> tuple[list[Path], dict[str, str]]:
    files: list[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend(sorted(f for f in pp.rglob("*") if f.is_file() and not f.name.startswith(".")))
        elif pp.is_file():
            files.append(pp)
    texts = {str(f): _read_text(f) for f in files if f.suffix.lower() in TEXT_EXTS}
    return files, texts


def speaker_index(texts: dict[str, str]) -> list[tuple[str, str]]:
    pairs = []
    for t in texts.values():
        for line in t.splitlines():
            m = SPEAKER_LINE_RE.search(line)
            if m:
                pairs.append((m.group(1).strip(), norm(m.group(2))))
    return pairs


def _count_grounded(num: str, unit: str, corpus: str) -> bool:
    n, u = re.escape(num), re.escape(unit)
    if re.search(rf"(?<![\d.]){n}(?![\d]|\.\d)\s?{u}", corpus, re.IGNORECASE):
        return True
    return bool(re.search(rf"[:=]\s*{n}(?![\d.])|[\"'“”]\s*{n}\s*[\"'“”]|,\s*{n}\s*,", corpus))


def check(report_text: str, source_paths: list[str], timeline_text: str = "") -> dict[str, Any]:
    if re.search(r"<[a-zA-Z/][^>]*>", report_text):
        report_text = TAG_RE.sub("\n", html.unescape(report_text))
    errors: list[str] = []
    warnings: list[str] = []
    files, texts = collect_sources(source_paths)
    corpus = norm("\n".join(texts.values()))
    corpus_digits = re.sub(r"(?<=\d),(?=\d{3})", "", "\n".join(texts.values()) + "\n" + timeline_text)
    speakers = speaker_index(texts)
    known_speakers = {s for s, _ in speakers}
    source_times = set(extract_timestamps("\n".join(texts.values()) + "\n" + timeline_text))
    basenames = {unicodedata.normalize("NFC", f.name).lower() for f in files}

    body = _strip_code(report_text)
    quotes_checked = 0
    for ln, line in enumerate(body.splitlines(), 1):
        abstain = bool(ABSTAIN_RE.search(line))

        def unsupported(msg: str) -> None:
            if abstain:
                warnings.append(f"{msg} (미확인 표기 줄 — 원본 근거 없음을 본문에 밝혔는지 확인)")
            else:
                errors.append(msg)

        quotes = [m.group(1) for rx in QUOTE_RES for m in rx.finditer(line)]
        quotes += [m.group(1) for m in EVIDENCE_TAG_RE.finditer(line)]
        for q in quotes:
            nq = norm(re.sub(r"<[^>]+>", "", q))
            if len(nq.replace(" ", "")) < MIN_QUOTE_CHARS:
                continue
            quotes_checked += 1
            if not texts:
                continue
            if nq not in corpus:
                unsupported(f"L{ln} 원본에 없는 인용: \"{nq[:40]}\" — 자료 폴더의 어떤 텍스트에도 이 문장이 없다(지어낸 발언/요약을 인용부호로 쓰지 말 것)")
                continue
            said_by = {s for s, utt in speakers if nq in utt or utt in nq and len(utt) >= MIN_QUOTE_CHARS}
            named = {s for s in known_speakers if s in line}
            if not said_by or not named:
                continue
            marked = {s for s in named if re.search(re.escape(s) + f"(?:{SPEAKER_MARK})", line)} if len(named) > 1 else named
            wrong = marked if marked and not (marked & said_by) else (named if not (named & said_by) else set())
            if wrong:
                errors.append(f"L{ln} 화자 불일치: \"{nq[:30]}\" 은 원본에서 {sorted(said_by)} 의 발언인데 보고서는 {sorted(wrong)} 로 적었다")
        if not texts:
            continue
        # 3) 시각 실재 (분 단위 시각만; 날짜만 있는 줄은 작성일 등일 수 있어 제외)
        for ts in extract_timestamps(line):
            if " " in ts and ts not in source_times:
                unsupported(f"L{ln} 원본/타임라인에 없는 시각: {ts[:16]} — 근거 자료의 시각만 쓸 것")
        for m in COUNT_RE.finditer(line):
            num = m.group(1).replace(",", "")
            if not _count_grounded(num, m.group(2), corpus_digits):
                unsupported(f"L{ln} 근거 없는 수치: {m.group(0)} — 자료나 분석 산출물(집계 JSON 등)에 이 값이 없다")
        for fm in FILE_TOKEN_RE.finditer(line):
            name = fm.group(1).strip().split("/")[-1].split("\\")[-1]
            name = re.sub(r"^.*?[:：]\s*", "", name).strip()
            if unicodedata.normalize("NFC", name).lower() not in basenames:
                unsupported(f"L{ln} 자료 폴더에 없는 파일: {name} — 첨부/증거로 적은 파일이 실제로 없다")

    has_claims = quotes_checked > 0 or bool(FILE_TOKEN_RE.search(body))
    if has_claims and not texts:
        if files:
            errors.append(
                "원본 텍스트 없음: 자료 폴더에 이미지·음성·PDF만 있어 인용을 대조할 수 없다 — OCR/STT/내보내기 텍스트를 자료 폴더에 함께 둘 것"
            )
        else:
            errors.append(
                "원본 자료 미제시: 보고서에 인용/첨부가 있으나 대조할 자료 폴더가 없다 — 보고서 옆 evidence/(또는 증거/, 자료/)에 원본을 두거나 --sources 로 지정할 것"
            )
    return {
        "sources": [str(f) for f in files],
        "text_sources": list(texts),
        "quotes_checked": quotes_checked,
        "errors": errors,
        "warnings": warnings,
        "verdict": "FAIL" if errors else "PASS",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="보고서-원본 자료 1:1 대조 (인용·화자·시각·건수·첨부)")
    ap.add_argument("report")
    ap.add_argument("--sources", nargs="+", default=[], help="자료 폴더 또는 파일")
    ap.add_argument("--timeline", help="타임라인 JSON (시각 대조 보강)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rp = Path(a.report)
    if not rp.is_file():
        print(f"report not found: {rp}", file=sys.stderr)
        return 2
    tl = Path(a.timeline).read_text(encoding="utf-8", errors="replace") if a.timeline and Path(a.timeline).is_file() else ""
    res = check(rp.read_text(encoding="utf-8", errors="replace"), a.sources, tl)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"[{res['verdict']}] 인용 {res['quotes_checked']}건 대조, 자료 {len(res['sources'])}개")
        for e in res["errors"]:
            print(f"  - ERROR: {e}")
        for w in res["warnings"]:
            print(f"  - WARN: {w}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
