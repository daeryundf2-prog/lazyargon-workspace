#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""source_grounding.py — 보고서 문장을 원본 자료(카톡·녹취·OCR 텍스트·첨부 파일)와 1:1 대조한다.

verify_report.py 의 해시·금지어 검사로는 잡히지 않는 환각을 결정적으로 차단한다 (LLM 0콜):
  1. 인용 실재: "…", “…”, ‘…’, '…'(한글 포함), 「…」, 『…』, 《…》, 〈…〉, <evidence>…</evidence> 안의 문장,
     줄을 넘긴 인용, 대화 로그 형식 줄('> 김철수: …', 시각이 있는 '김철수: …', 코드블록 안 로그),
     화자·발언 열이 있는 표의 발언 칸이 원본 텍스트에 그대로 있어야 한다.
     법령·문서 제목(「민법」, 「개인정보 보호법」 제17조)과 정의어((이하 "이 사건 계약"이라 한다))는 제외한다.
  2. 화자 귀속: 인용 줄에 화자가 한 명 언급되면 원본 발언자와 같아야 한다. 두 명 이상이면 그중 누구도
     발언자가 아닐 때, 또는 조사(은/는/이/가/께서/의/에게서/한테서/로부터), '이름 :', 인용 바로 앞 이름으로
     드러난 말한 사람이 원본 발언자가 아닐 때 오류다.
  3. 시각 실재: 보고서의 분 단위 시각(2026-03-12 14:09, 2026.03.12 14:09, 2026년 3월 12일 오후 2:09,
     연도 없는 3월 12일 14:09)이 원본/타임라인에 있어야 하고, 인용과 같은 줄의 시각은 그 발언의 원본 시각이어야 한다.
  4. 수치 실재: "N건/개/회/통/명/차례/%/MB/페이지/프레임/시간/분간/초간"과 금액("N원", "N만원")이 원본에 같은
     단위로 있거나, 집계 JSON/CSV에서 단위에 맞는 키(명→speakers, 건→messages 등)의 값이어야 한다.
  5. 첨부 실재: 보고서가 언급한 증거 파일명(.jpg .m4a .pdf .hwp …)이 자료 폴더에 실제로 있어야 한다.
명령·경로가 담긴 인라인 코드(`python …`, `evidence/…`)는 검사하지 않는다(한글 문장을 감싼 코드는 검사한다). '미확인/미측정/[INSUFFICIENT_DATA]'가 그 항목 뒤에서 단정 어미(…다) 없이 이어지면
(예: "…"는 자료에서 미확인) 원본에 없는 인용·시각·수치·파일을 경고로 보고한다. 단정한 뒤 괄호로 덧붙인 '(일부 미확인)'은
유보로 치지 않는다. 화자 오류는 어디서든 오류다.
원본이 이미지·음성·PDF뿐이면 텍스트 대조가 불가능하므로, OCR/STT 텍스트를 자료 폴더에 함께 두어야 한다.
결정적으로 못 잡는 것: 인용부호 없는 간접 화법("돈을 보냈다고 말했다"), 별칭·지위어(김씨, 피고)로 쓴 화자,
한글 수사(열다섯 건), 3자 이하 짧은 인용. 이것은 사람이 읽고 확인해야 한다.

CLI: python scripts/source_grounding.py 보고서.md --sources 자료폴더 [파일...] [--timeline events.json] [--json]
"""
from __future__ import annotations

import argparse
import csv
import html
import io
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
    re.compile(r"‘([^’\n]{2,300})’"),
    re.compile(r"(?<![A-Za-z0-9])'([^'\n]{2,300})'(?![A-Za-z0-9])"),
    re.compile(r"「([^」\n]{2,300})」"),
    re.compile(r"『([^』\n]{2,300})』"),
    re.compile(r"《([^》\n]{2,300})》"),
    re.compile(r"〈([^〉\n]{2,300})〉"),
]
QUOTE_CHARS_RE = re.compile(r"[\"“”‘’「」『』《》〈〉]")
EVIDENCE_TAG_RE = re.compile(r"<evidence(?:\s[^>]*)?>(.*?)</evidence>", re.IGNORECASE | re.DOTALL)
COUNT_RE = re.compile(
    r"(?<![A-Za-z\d.,제])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?"
    r"(%|건|개(?![월년])|회(?![사의원신차])|통(?![화장신보])|명(?![의령시확백])|차례|시간(?![대표])|분간|초간|"
    r"KB|MB|GB|TB|바이트|페이지|프레임)(?![가-힣]*호증)"
)
MONEY_RE = re.compile(r"(?<![A-Za-z\d.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(억|천만|백만|만|천)?\s?원(?![고본래문인칙장활형])")
MONEY_MULT = {"억": 10**8, "천만": 10**7, "백만": 10**6, "만": 10**4, "천": 10**3, None: 1, "": 1}
UNIT_KEYS = {
    "명": r"speaker|person|people|participant|user|member|sender|명|인원|화자|참여|사람",
    "%": r"pct|percent|ratio|rate|share|비율|율|%",
    "size": r"size|byte|kb|mb|gb|tb|용량|크기",
    "페이지": r"page|페이지|쪽",
    "프레임": r"frame|프레임",
    "dur": r"duration|sec|min|hour|time|length|시간|길이",
    "count": r"count|total|num|^n$|_n$|message|msg|call|item|file|hit|record|row|entr|event|chat|photo|image|건|개|통|회|수",
}
UNIT_CLASS = {"명": "명", "%": "%", "KB": "size", "MB": "size", "GB": "size", "TB": "size", "바이트": "size",
              "페이지": "페이지", "프레임": "프레임", "시간": "dur", "분간": "dur", "초간": "dur"}
INLINE_TAG_RE = re.compile(r"</?(?:a|abbr|b|cite|code|em|font|i|mark|q|s|small|span|strong|sub|sup|u)\b[^>]*>", re.IGNORECASE)
TAG_RE = re.compile(r"<(?!/?evidence\b)[a-zA-Z/][^>]*>", re.IGNORECASE)
SPEAKER_LINE_RE = re.compile(r"(?:^|[,\]\)]\s*)([가-힣A-Za-z][가-힣A-Za-z0-9 ]{0,14}?)\s*:\s*(.+)$")
ABSTAIN_RE = re.compile(r"미확인|미측정|INSUFFICIENT_DATA|UNVERIFIED|판단\s*불능")
ASSERT_END_RE = re.compile(r"다(?:[.)\]\s,(]|$)")
MIN_QUOTE_CHARS = 4
SPEAKER_MARK = r"\s*(?:께서|에게서|한테서|로부터|은|는|이|가|의)(?![가-힣])|\s*[:：]|\s*[,]?\s*(?=[\"“「『‘'《〈])"
HHMM_RE = re.compile(r"\d{1,2}\s*(?::\d{2}|시)")
DOT_DT_RE = re.compile(r"(?<!\d)(\d{4})[./](\d{1,2})[./](\d{1,2})\.?\s+(\d{1,2}):(\d{2})(?!\d)")
YEARLESS_RE = re.compile(r"(?<!\d)(\d{1,2})월\s*(\d{1,2})일\s*(?:(오전|오후)\s*)?(\d{1,2})(?::(\d{2})|\s*시(?:\s*(\d{1,2})\s*분)?)")
TITLE_END_RE = re.compile(r"(?:법|법률|시행령|시행규칙|령|규칙|규정|조례|협약|지침|기준|가이드라인)$")
TABLE_SPEAKER_COL = re.compile(r"화자|발신|발언자|작성자|송신|보낸|speaker|sender|from", re.IGNORECASE)
TABLE_TEXT_COL = re.compile(r"발언|메시지|대화|원문|인용|진술|utterance|message", re.IGNORECASE)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFC", html.unescape(s))
    s = re.sub(r"[‘’'`]", "'", s)
    s = re.sub(r"[“”\"]", '"', s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().strip(" .,!?…~").strip()


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


def speaker_index(texts: dict[str, str]) -> list[tuple[str, str, frozenset[str]]]:
    """(화자, 정규화 발언, 그 줄의 분 단위 시각) 목록."""
    rows = []
    for t in texts.values():
        for line in t.splitlines():
            m = SPEAKER_LINE_RE.search(line)
            if m:
                times = frozenset(ts[:16] for ts in extract_timestamps(line) if " " in ts)
                rows.append((m.group(1).strip(), norm(m.group(2)), times))
    return rows


def _num(v: Any) -> str | None:
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(str(v).replace(",", ""))
    except ValueError:
        return None
    return str(int(f)) if f == int(f) else str(f)


def structured_values(texts: dict[str, str]) -> list[tuple[str, str]]:
    """집계 산출물(JSON/JSONL/CSV/TSV)의 (키 경로, 숫자 값) 목록."""
    out: list[tuple[str, str]] = []

    def walk(node: Any, key: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{key}.{k}" if key else str(k))
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        else:
            n = _num(node)
            if n is not None:
                out.append((key.lower(), n))

    for name, t in texts.items():
        suf = Path(name).suffix.lower()
        if suf == ".json":
            try:
                walk(json.loads(t), "")
            except ValueError:
                pass
        elif suf == ".jsonl":
            for line in t.splitlines():
                try:
                    walk(json.loads(line), "")
                except ValueError:
                    continue
        elif suf in {".csv", ".tsv"}:
            rows = list(csv.reader(io.StringIO(t), delimiter="\t" if suf == ".tsv" else ","))
            if rows:
                header = [h.strip().lower() for h in rows[0]]
                for r in rows[1:]:
                    for h, cell in zip(header, r):
                        n = _num(cell.strip())
                        if n is not None:
                            out.append((h, n))
    return out


def _count_grounded(num: str, unit: str, corpus: str, struct: list[tuple[str, str]]) -> bool:
    n, u = re.escape(num), re.escape(unit)
    if re.search(rf"(?<![\d.]){n}(?![\d]|\.\d)\s?{u}", corpus, re.IGNORECASE):
        return True
    keys = re.compile(UNIT_KEYS[UNIT_CLASS.get(unit, "count")], re.IGNORECASE)
    target = _num(num)
    return any(v == target and keys.search(k.split(".")[-1] or k) for k, v in struct)


def _money_grounded(num: str, mult: str | None, corpus: str, struct: list[tuple[str, str]]) -> bool:
    value = int(round(float(num) * MONEY_MULT[mult]))
    pats = [rf"(?<![\d.]){re.escape(num)}\s?{mult or ''}\s?원", rf"(?<![\d.]){value}(?![\d])"]
    if value % 10**8 == 0:
        pats.append(rf"(?<![\d.]){value // 10**8}\s?억")
    if value % 10**4 == 0:
        pats.append(rf"(?<![\d.]){value // 10**4}\s?만")
    if any(re.search(p, corpus) for p in pats):
        return True
    return any(v == str(value) for _, v in struct)


def _hedged(line: str, start: int, end: int) -> bool:
    """항목 뒤에 단정 어미 없이 미확인이 오거나, '미확인:' 라벨 뒤에 있으면 유보다."""
    for m in ABSTAIN_RE.finditer(line):
        if m.start() >= end and not ASSERT_END_RE.search(line[end:m.start()]):
            return True
        if m.end() <= start and re.match(r"[^:：]{0,12}[:：]", line[m.end():start]):
            return True
    return False


def _report_times(line: str) -> tuple[set[str], set[str]]:
    """(연도 포함 'YYYY-MM-DD HH:MM', 연도 없는 'MM-DD HH:MM')."""
    full = {ts[:16] for ts in extract_timestamps(line) if " " in ts}
    for m in DOT_DT_RE.finditer(line):
        y, mo, d, h, mi = m.groups()
        full.add(f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(h):02d}:{mi}")
    yearless = set()
    for m in YEARLESS_RE.finditer(line):
        if re.search(r"\d{4}\s*년\s*$", line[: m.start()]):
            continue
        mo, d, ampm, h, mi1, mi2 = m.groups()
        hour = int(h)
        if ampm == "오후" and hour < 12:
            hour += 12
        elif ampm == "오전" and hour == 12:
            hour = 0
        yearless.add(f"{int(mo):02d}-{int(d):02d} {hour:02d}:{int(mi1 or mi2 or 0):02d}")
    return full, yearless


def _skip_quote(q: str, line: str, start: int, end: int) -> bool:
    if TITLE_END_RE.search(q.strip()) or re.match(r"\s*제\s*\d+\s*조", line[end:]):
        return True
    if re.search(r"이하\s*$", line[:start]):
        return True
    return bool(re.match(r"\s*(?:이?라\s*(?:한다|칭한다|함)|이?라고\s*(?:한다|칭한다))", line[end:]))


def _clean_report(text: str) -> tuple[list[str], set[int]]:
    if re.search(r"<[a-zA-Z/][^>]*>", text):
        text = html.unescape(TAG_RE.sub("\n", INLINE_TAG_RE.sub("", text)))
    lines = text.splitlines()
    fenced: set[int] = set()
    inside = False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            inside = not inside
            fenced.add(i)
            lines[i] = ""
        elif inside:
            fenced.add(i)
    def code_span(m: re.Match[str]) -> str:
        inner = m.group(1)
        if re.search(r"[가-힣]", inner) and not re.search(r"[/\\=$]|--|\.\w{1,5}\b|\b(?:python|node|bash|scripts)\b", inner):
            return inner
        return ""

    lines = [ln if i in fenced else re.sub(r"`([^`\n]*)`", code_span, ln) for i, ln in enumerate(lines)]
    return lines, fenced


def _quote_items(i: int, lines: list[str], fenced: set[int], speakers_by_len: list[str], table: dict[str, Any]):
    """(인용, 시작, 끝, 명시 화자, 문맥 줄) 목록."""
    line = lines[i]
    items = []
    if i not in fenced:
        for rx in QUOTE_RES:
            for m in rx.finditer(line):
                q = m.group(1)
                if rx.pattern.startswith("(?<![A-Za-z0-9])'") and not re.search(r"[가-힣]", q):
                    continue
                if not _skip_quote(q, line, m.start(), m.end()):
                    items.append((q, m.start(), m.end(), None, line))
        items += [(m.group(1), m.start(), m.end(), None, line) for m in EVIDENCE_TAG_RE.finditer(line)]
        if line.count('"') % 2 == 1 or line.count("“") > line.count("”"):
            joined = line
            for j in range(i + 1, min(i + 4, len(lines))):
                joined += " " + lines[j]
                if joined.count('"') % 2 == 0 and joined.count("“") <= joined.count("”"):
                    break
            for rx in QUOTE_RES[:2]:
                for m in rx.finditer(joined):
                    if m.start() < len(line) < m.end():
                        items.append((m.group(1), m.start(), m.end(), None, joined))
    chat_like = i in fenced or line.lstrip().startswith(">") or HHMM_RE.search(line)
    if chat_like:
        for s in speakers_by_len:
            m = re.search(r"(?:^|[\s,\]\)>|])" + re.escape(s) + r"\s*[:：]\s*(.+?)\s*\|?\s*$", line)
            if m:
                utt = m.group(1)
                if not QUOTE_CHARS_RE.search(utt):
                    items.append((utt, m.start(1), m.end(1), s, line))
                break
    cells = [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else None
    if cells and table.get("text") is not None and len(cells) > table["text"]:
        utt = cells[table["text"]]
        spk = cells[table["speaker"]] if len(cells) > table["speaker"] else ""
        if utt and not QUOTE_CHARS_RE.search(utt):
            pos = line.find(utt)
            items.append((utt, pos, pos + len(utt), spk if spk in speakers_by_len else None, line))
    return items


def check(report_text: str, source_paths: list[str], timeline_text: str = "") -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    files, texts = collect_sources(source_paths)
    corpus = norm("\n".join(texts.values()))
    corpus_digits = re.sub(r"(?<=\d),(?=\d{3})", "", "\n".join(texts.values()) + "\n" + timeline_text)
    struct = structured_values(texts)
    speakers = speaker_index(texts)
    known_speakers = {s for s, _, _ in speakers}
    speakers_by_len = sorted(known_speakers, key=len, reverse=True)
    all_times = extract_timestamps("\n".join(texts.values()) + "\n" + timeline_text)
    source_times = {ts[:16] for ts in all_times if " " in ts}
    source_yearless = {ts[5:16] for ts in source_times}
    basenames = {unicodedata.normalize("NFC", f.name).lower() for f in files}

    lines, fenced = _clean_report(report_text)
    quotes_checked = 0
    table: dict[str, Any] = {}
    for idx, line in enumerate(lines):
        ln = idx + 1
        stripped = line.strip()
        if stripped.startswith("|") and idx + 1 < len(lines) and re.match(r"^\|?\s*:?-{3,}", lines[idx + 1].strip()):
            heads = [c.strip() for c in stripped.strip("|").split("|")]
            sc = next((k for k, h in enumerate(heads) if TABLE_SPEAKER_COL.search(h)), None)
            tc = next((k for k, h in enumerate(heads) if TABLE_TEXT_COL.search(h)), None)
            table = {"speaker": sc, "text": tc} if sc is not None and tc is not None else {}
            continue
        if not stripped.startswith("|"):
            table = {}

        def unsupported(msg: str, start: int, end: int, ctx: str = line) -> None:
            if _hedged(ctx, start, end):
                warnings.append(f"{msg} (미확인으로 유보한 항목 — 원본 근거 없음을 본문에 밝혔는지 확인)")
            else:
                errors.append(msg)

        full_times, yearless_times = _report_times(line)
        for q, start, end, explicit, ctx in _quote_items(idx, lines, fenced, speakers_by_len, table):
            nq = norm(re.sub(r"<[^>]+>", "", q))
            if len(nq.replace(" ", "")) < MIN_QUOTE_CHARS:
                continue
            quotes_checked += 1
            if not texts:
                continue
            if nq not in corpus:
                unsupported(f"L{ln} 원본에 없는 인용: \"{nq[:40]}\" — 자료 폴더의 어떤 텍스트에도 이 문장이 없다(지어낸 발언/요약을 인용부호로 쓰지 말 것)", start, end, ctx)
                continue
            hits = [(s, t) for s, utt, t in speakers if nq in utt or (utt in nq and len(utt) >= MIN_QUOTE_CHARS)]
            said_by = {s for s, _ in hits}
            src_times = set().union(*(t for _, t in hits)) if hits else set()
            if src_times and full_times and not (full_times & src_times):
                errors.append(f"L{ln} 시각-발언 불일치: \"{nq[:30]}\" 의 원본 시각은 {sorted(src_times)} 인데 보고서는 {sorted(full_times)} 로 적었다")
            if not said_by:
                continue
            if explicit:
                wrong = {explicit} - said_by
            else:
                named = {s for s in known_speakers if s in ctx}
                if not named:
                    continue
                marked = {s for s in named if re.search(re.escape(s) + f"(?:{SPEAKER_MARK})", ctx)} if len(named) > 1 else named
                wrong = marked if marked and not (marked & said_by) else (named if not (named & said_by) else set())
            if wrong:
                errors.append(f"L{ln} 화자 불일치: \"{nq[:30]}\" 은 원본에서 {sorted(said_by)} 의 발언인데 보고서는 {sorted(wrong)} 로 적었다")
        if not texts or idx in fenced:
            continue
        tpos = HHMM_RE.search(line)
        tstart, tend = (tpos.start(), tpos.end()) if tpos else (0, 0)
        for ts in sorted(full_times - source_times):
            unsupported(f"L{ln} 원본/타임라인에 없는 시각: {ts} — 근거 자료의 시각만 쓸 것", tstart, tend)
        for ts in sorted(yearless_times - source_yearless):
            unsupported(f"L{ln} 원본/타임라인에 없는 시각: {ts}(연도 없음) — 근거 자료의 시각만 쓸 것", tstart, tend)
        for m in COUNT_RE.finditer(line):
            num = m.group(1).replace(",", "")
            if not _count_grounded(num, m.group(2), corpus_digits, struct):
                unsupported(f"L{ln} 근거 없는 수치: {m.group(0).strip()} — 자료나 분석 산출물(집계 JSON 등)에 이 값이 없다", m.start(), m.end())
        for m in MONEY_RE.finditer(line):
            if not _money_grounded(m.group(1).replace(",", ""), m.group(2), corpus_digits, struct):
                unsupported(f"L{ln} 근거 없는 금액: {m.group(0).strip()} — 자료에 이 금액이 없다", m.start(), m.end())
        for fm in FILE_TOKEN_RE.finditer(line):
            name = fm.group(1).strip().split("/")[-1].split("\\")[-1]
            name = re.sub(r"^.*?[:：]\s*", "", name).strip()
            words = name.split()
            tails = [" ".join(words[k:]) for k in range(len(words))]
            if all(unicodedata.normalize("NFC", t).lower() not in basenames for t in tails):
                name = tails[-1] if tails else name
                unsupported(f"L{ln} 자료 폴더에 없는 파일: {name} — 첨부/증거로 적은 파일이 실제로 없다", fm.start(), fm.end())

    body = "\n".join(lines)
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
    ap = argparse.ArgumentParser(description="보고서-원본 자료 1:1 대조 (인용·화자·시각·건수·금액·첨부)")
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
