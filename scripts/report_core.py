#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report_core.py — verify_report 검증 함수 모음.

verify_report.py 에서 분리(C2). 스캔/추출/로딩/바인딩/헬스체크 함수만 모은다.
CLI 오케스트레이션은 verify_report.py 가 유지한다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

try:
    from scripts.report_patterns import (
        CERTAINTY_ASSERTION_RES,
        DOT_DATE_RE,
        EVIDENCE_TAG_RE,
        FORBIDDEN_PHRASES,
        HASH_VALUE_RE,
        ISO_DATE_RE,
        ISO_DT_RE,
        KOR_DT_RE,
        NEGATION_RE,
    )
except ImportError:  # scripts/ 가 sys.path 에 직접 있는 경우
    from report_patterns import (
        CERTAINTY_ASSERTION_RES,
        DOT_DATE_RE,
        EVIDENCE_TAG_RE,
        FORBIDDEN_PHRASES,
        HASH_VALUE_RE,
        ISO_DATE_RE,
        ISO_DT_RE,
        KOR_DT_RE,
        NEGATION_RE,
    )


def scan_certainty_variants(text: str) -> list[str]:
    hits = []
    for pat, label in CERTAINTY_ASSERTION_RES:
        for m in pat.finditer(text):
            after = text[m.end(): m.end() + 20]
            if not NEGATION_RE.match(after):
                hits.append(f"{label}: '{m.group(0)}'")
                break
    return hits


def scan_forbidden(text: str) -> list[str]:
    hits = []
    for phrase in FORBIDDEN_PHRASES:
        start = 0
        while True:
            idx = text.find(phrase, start)
            if idx == -1:
                break
            after = text[idx + len(phrase): idx + len(phrase) + 20]
            if not NEGATION_RE.match(after):
                hits.append(phrase)
                break
            start = idx + len(phrase)
    return hits


def extract_hashes(text: str) -> list[str]:
    """SHA-256 (64hex 전체) + 문맥 라벨이 붙은 MD5(32hex)/SHA-1(40hex).

    32/40 hex 는 무라벨 오탐이 많아 MD5/SHA-1 라벨이 같은 줄에 있을 때만 수집한다.

    줄바꿈·공백으로 분할된 64hex 도 잡는다(표 정렬·하드랩). 개행 결합은 두
    32hex 해시를 하나로 합쳐 환영 해시를 만들 수 있지만, 그 결과는 '근거 없는
    해시' 판정(실패폐쇄 방향)으로 귀결되므로 안전한 쪽의 오류다.
    """
    found = re.findall(r"\b[a-fA-F0-9]{64}\b", text)
    have = {h.lower() for h in found}
    for line in text.splitlines():
        if re.search(r"\bMD5\b|\bSHA-?1\b|md5_legacy", line, re.IGNORECASE):
            for pat in (r"\b[a-fA-F0-9]{40}\b", r"\b[a-fA-F0-9]{32}\b"):
                for h in re.findall(pat, line):
                    if h.lower() not in have:
                        found.append(h)
                        have.add(h.lower())
    # 분할 해시: 개행/공백이 hex 문자 사이에 낀 경우만 결합해 다시 찾는다.
    compact = re.sub(r"(?<=[a-fA-F0-9])[ \t]*\r?\n[ \t]*(?=[a-fA-F0-9])", "", text)
    if compact != text:
        for h in re.findall(r"\b[a-fA-F0-9]{64}\b", compact):
            if h.lower() not in have and h not in text:
                found.append(h)
                have.add(h.lower())
    return found


def _h12_to_24(ampm: str | None, hour: int | None) -> int | None:
    if hour is None:
        return None
    if ampm is None:
        return hour
    if ampm == "오후" and hour != 12:
        return hour + 12
    if ampm == "오전" and hour == 12:
        return 0
    return hour


def extract_timestamps(text: str) -> list[str]:
    """정규형 집합: 'YYYY-MM-DD HH:MM(:SS)' 와 'YYYY-MM-DD'."""
    out: set[str] = set()
    for m in ISO_DT_RE.finditer(text):
        y, mo, d, h, mi, s = m.groups()
        out.add(f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(h):02d}:{mi}:{int(s) if s else 0:02d}")
    for m in KOR_DT_RE.finditer(text):
        date = f"{int(m.group('y')):04d}-{int(m.group('mo')):02d}-{int(m.group('d')):02d}"
        if m.group("hkor"):
            hour = int(m.group("hkor"))
            minute = int(m.group("mikor") or 0)
        elif m.group("hiso"):
            hour = int(m.group("hiso"))
            minute = int(m.group("miiso"))
        else:
            out.add(date)
            continue
        hour = _h12_to_24(m.group("ampm"), hour)
        out.add(f"{date} {hour:02d}:{minute:02d}:{0:02d}")
    for m in DOT_DATE_RE.finditer(text):
        y, mo, d = m.groups()
        out.add(f"{int(y):04d}-{int(mo):02d}-{int(d):02d}")
    for m in ISO_DATE_RE.finditer(text):
        y, mo, d = m.groups()
        out.add(f"{int(y):04d}-{int(mo):02d}-{int(d):02d}")
    return sorted(out)


def read_text_smart(path: Path, max_bytes: int = 8 * 1024 * 1024) -> tuple[str, str, bool]:
    """BOM/UTF-16/CP949를 순서대로 시도한다. 모두 실패하면 치환 문자로 읽고 lossy=True.

    구버전의 errors="ignore" 는 UTF-16 (Windows PowerShell Out-File 기본값) 입력을
    그대로 mojibake 로 만들어 금지 문구·해시 검출을 모두 놓쳤다.
    대용량 파일은 앞 max_bytes까지만 읽고 lossy=True로 표시한다 (Lazy Read:
    전체 로딩 OOM 방지, 잘림은 호출자가 경고한다).
    """
    size = path.stat().st_size if path.exists() else 0
    truncated = size > max_bytes
    with open(path, "rb") as f:
        raw = f.read(max_bytes + 1 if truncated else max_bytes)
    if truncated:
        raw = raw[:max_bytes]
    for enc in ("utf-8-sig", "utf-16", "cp949"):
        try:
            return raw.decode(enc), enc + ("(truncated)" if truncated else ""), truncated
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(lossy)" + ("(truncated)" if truncated else ""), True


def load_evidence_hashes(evidence_paths: list[str]) -> set[str]:
    hashes: set[str] = set()
    for p in evidence_paths:
        path = Path(p)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        hashes.update(h.lower() for h in extract_hashes(text))
        # json / jsonl 구조 필드 (sha256, md5, sha1)
        objs: list = []
        try:
            data = json.loads(text)
            objs.append(data)
        except Exception:
            for line in text.splitlines():
                try:
                    objs.append(json.loads(line))
                except Exception:
                    pass
        for obj in objs:
            items = obj if isinstance(obj, list) else [obj]
            for item in items:
                if isinstance(item, dict):
                    for key, val in item.items():
                        if isinstance(val, str) and HASH_VALUE_RE.match(val):
                            hashes.add(val.lower())
    return hashes


def _normalize_file_token(tok: str) -> str:
    """파일 토큰 정규화: 경로는 basename으로, 비교는 소문자(Windows/macOS
    파일시스템은 대소문자 무관)로 통일한다."""
    return tok.strip().replace("\\", "/").rstrip("/").split("/")[-1].casefold()


def load_evidence_hash_file_pairs(evidence_paths: list[str]) -> dict[str, list[str]]:
    """evidence JSON에서 {해시: [파일명...]} 매핑을 추출한다.

    지원 스키마: dict의 (path|file|filename|name)↔(sha256|sha1|md5|hash) 필드 쌍,
    부모 dict의 파일명 + 자식 dict의 해시(중첩 스키마), 그리고 "파일명 ... 64hex"
    형태의 텍스트 표.
    """
    pairs: dict[str, list[str]] = {}

    def _add(h: str, fname: str):
        h = h.strip().lower()
        fname = _normalize_file_token(fname)
        if not HASH_VALUE_RE.match(h) or not fname:
            return
        pairs.setdefault(h, [])
        if fname not in pairs[h]:
            pairs[h].append(fname)

    # 파일명 후보 키 우선순위 — dict 순서가 아닌 명시적 우선순위로 고정.
    # 'name'은 확장자가 있는(=실제 파일명인) 값만 인정해 도구명/기관명 오염 방지.
    def _fname_candidates(obj: dict) -> list[str]:
        found: list[str] = []
        for key in ("filename", "file_name", "file", "path", "target"):
            v = obj.get(key)
            if isinstance(v, str) and v.strip():
                found.append(v)
                break
        name_v = obj.get("name")
        if isinstance(name_v, str) and re.search(r"\.[A-Za-z0-9]{1,8}$", name_v.strip()):
            found.append(name_v)
        return found

    def _walk(obj, parent_fname: str | None = None):
        if isinstance(obj, list):
            for item in obj:
                _walk(item, parent_fname)
            return
        if not isinstance(obj, dict):
            return
        # 이 객체 안의 해시들: 같은 객체의 파일명 후보, 없으면 부모의 파일명
        fnames = _fname_candidates(obj)
        inherited = fnames or ([parent_fname] if parent_fname else [])
        for key, val in obj.items():
            if not isinstance(val, str):
                continue
            val_clean = val.strip()
            if HASH_VALUE_RE.match(val_clean) and re.search(
                r"sha|md5|hash|digest", key, re.IGNORECASE
            ):
                for fname in inherited:
                    _add(val_clean, fname)
        # 자식 순회: 이 객체의 파일명을 물려준다 (file/meta 중첩 스키마 결합)
        child_fname = fnames[0] if fnames else parent_fname
        for val in obj.values():
            if isinstance(val, (dict, list)):
                _walk(val, child_fname)

    for p in evidence_paths:
        path = Path(p)
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        try:
            data = json.loads(text)
            _walk(data)
        except Exception:
            for line in text.splitlines():
                parsed = False
                try:
                    _walk(json.loads(line))
                    parsed = True
                except Exception:
                    pass
                if parsed:
                    continue  # JSON 라인은 표 regex 이중 처리 생략
                # 텍스트 표 형태: "파일명 <경로/확장자> ... 64hex"
                for m in re.finditer(r"([^\s|]+\.[A-Za-z0-9]{1,8})\s*\|?\s*([a-fA-F0-9]{64})\b", line):
                    _add(m.group(2), m.group(1))
                for m in re.finditer(r"\b([a-fA-F0-9]{64})\b\s*\|?\s*([^\s|]+\.[A-Za-z0-9]{1,8})", line):
                    _add(m.group(1), m.group(2))
    return pairs


def check_hash_file_binding(report_text: str, evidence_pairs: dict[str, list[str]]) -> list[str]:
    """해시-파일명 인접성 검증 (Proximity Binding).

    보고서에서 해시가 나온 줄의 ±2줄 윈도우에 적힌 파일명이, evidence의 해당
    해시 소유 파일명과 일치하는지 대조한다. 정상 해시를 악의적 서술(다른
    파일명)에 재사용하면 FAIL. 파일명 후보는 basename+casefold로 정규화하고,
    소수점 버전(2.3)·IP·URL 등 확장자에 영문자가 없는 유사 토큰은 제외한다.

    스키마 강제 2종 추가:
    - 표 행 엄격: 해시가 마크다운 표 행(`|`) 안에 있으면 같은 행에 소유
      파일명이 있어야 한다. 같은 행에 다른 파일명만 있으면 즉시 위반.
    - 미결합 경고: ±2줄 윈도우에 파일명이 전혀 없으면 스키마 위반(WARN)으로
      기록한다 (3줄 이상 떨어진 변칙 서술 방지).
    """
    violations: list[str] = []
    seen: set[tuple[str, int]] = set()
    if not evidence_pairs:
        return violations
    lines = report_text.splitlines()
    # <evidence> 태그 안의 해시는 태그 귀속으로 이미 그라운딩되므로
    # 미결합 스키마 경고에서 제외한다 (태그 밖 서술만 검사).
    tag_spans: list[tuple[int, int]] = [
        (m.start(), m.end()) for m in EVIDENCE_TAG_RE.finditer(report_text)
    ]
    line_offsets: list[int] = []
    _off = 0
    for ln in lines:
        line_offsets.append(_off)
        _off += len(ln) + 1

    def _in_evidence_tag(abs_pos: int) -> bool:
        return any(s <= abs_pos < e for s, e in tag_spans)

    # 태그 귀속 해시 집합: 본문에 <evidence>H</evidence>로 한 번이라도
    # 인용된 해시는 파일명 동행 없이도 그라운딩된 것으로 본다 (재언급 오탐 방지).
    tagged_hashes: set[str] = set()
    for tm in EVIDENCE_TAG_RE.finditer(report_text):
        for hm in re.finditer(r"\b([a-fA-F0-9]{64})\b", tm.group(1)):
            tagged_hashes.add(hm.group(1).lower())
    # 확장자에 최소 1개 영문자를 요구해 2.3 / 192.168.1.10 / example.com 배제.
    # 확장자 뒤 한국어 조사(의/은/는/이/가/을/를/도/에/에서/와/과/로)를 허용해
    # "secret.zip의 해시" 형태의 파일명 토큰도 잡는다.
    file_token_re = re.compile(
        r"([^\s|]+\.[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]{0,7})(?:의|은|는|이|가|을|를|도|에|에서|와|과|로|으로|랑|이랑)?(?=[\s,.:;)\]|가-힣]|$)"
    )
    for li, line in enumerate(lines):
        for m in re.finditer(r"\b([a-fA-F0-9]{64})\b", line):
            h = m.group(1).lower()
            owners = evidence_pairs.get(h)
            if not owners:
                continue  # 미등록 해시는 기존 '근거 없는 해시' 검사가 처리
            abs_pos = line_offsets[li] + m.start()
            in_tag = _in_evidence_tag(abs_pos)
            # 해시와 파일명이 인접(같은 줄 또는 ±2줄)한 파일명 수집
            window_files: set[str] = set()
            for wli in range(max(0, li - 2), min(len(lines), li + 3)):
                for fm in file_token_re.finditer(lines[wli]):
                    window_files.add(_normalize_file_token(fm.group(1)))
            owners_norm = [_normalize_file_token(o) for o in owners]
            if not window_files:
                if h in tagged_hashes:
                    continue  # 태그 귀속 해시는 파일명 동행 불필요
                key = (h, li)
                if key not in seen:
                    seen.add(key)
                    violations.append(
                        f"[SCHEMA-WARN] 해시-파일 결합 스키마 위반: 해시 {h[:16]}... 주변 ±2줄에 파일명이 없어 "
                        f"어느 파일의 해시인지 검증할 수 없음 — 해시와 파일명을 같은 표 행 또는 인접 줄에 기재하십시오"
                    )
                continue
            # 표 행 엄격: '|' 포함 행에서는 같은 행의 파일명을 우선 대조한다.
            if "|" in line:
                same_row = {_normalize_file_token(fm.group(1)) for fm in file_token_re.finditer(line)}
                if same_row and not any(o in same_row for o in owners_norm):
                    key = (h, li)
                    if key not in seen:
                        seen.add(key)
                        violations.append(
                            f"해시-파일 결합 불일치(표 행): 해시 {h[:16]}... 와 같은 행에 "
                            f"{sorted(same_row)[:2]} 가 있으나 evidence 소유 파일은 "
                            f"{owners[:2]} 임 — 표 행의 파일명-해시 쌍을 확인하십시오"
                        )
                    continue
            if not any(o in window_files for o in owners_norm):
                key = (h, li)
                if key in seen:
                    continue
                seen.add(key)
                violations.append(
                    f"해시-파일 결합 불일치: 해시 {h[:16]}... 가 인접 줄에서 "
                    f"{sorted(window_files)[:2]} 와 함께 서술되었으나 evidence에서 이 해시의 소유 파일은 "
                    f"{owners[:2]} 임 — 정상 해시를 다른 파일 서술에 재사용했는지 확인하십시오"
                )
    return violations


def run_forensic_health_check() -> dict:
    """Run comprehensive Section 5.1 & Section 6 forensic factuality health check suite.
    Scores 12 categories (10 points each = 120 points total; pass mark 100%).
    Returns health check report with score and test results.
    """
    import io
    import tempfile
    from contextlib import redirect_stdout, redirect_stderr

    try:
        from scripts.verify_report import main as _main
    except ImportError:
        from verify_report import main as _main

    tests = [
        # 1. Forbidden phrases: Must block forbidden certainty words
        (
            "forbidden_phrases_blocked",
            "이 증거는 법원에 유효하며 피의자의 유출이 명백히 입증되었습니다.",
            lambda out, code: code != 0 and any("금지 문구" in e for e in out.get("errors", [])),
        ),
        # 2. Hash grounding: Must block ungrounded 64-char hex hash
        (
            "orphan_hash_blocked",
            "분석 결과 악성코드의 해시는 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 입니다.",
            lambda out, code: code != 0 and any("근거 없는 해시" in e for e in out.get("errors", [])),
        ),
        # 3. Statutory bounds: Must block out-of-bounds statute article
        (
            "statutory_bounds_blocked",
            "정보통신망법 제100조에 따라 처벌을 의뢰합니다.",
            lambda out, code: code != 0 and any("허위 조문 날조" in e for e in out.get("errors", [])),
        ),
        # 4. Precedents sanity: Must block future year precedent
        (
            "precedents_future_blocked",
            "대법원 2099도12345 판결 취지를 원용합니다.",
            lambda out, code: code != 0 and any("미래 연도 판결" in e for e in out.get("errors", [])),
        ),
        # 5. Agency & Academic citations: Must block fabricated agencies & fake academic journals/future citations (Section 5.1 #2 & #3)
        (
            "agency_and_academic_blocked",
            "사이버수사처 및 대한인공지능법학회지, 홍길동 교수의 2099년 학술지 논문 인용.",
            lambda out, code: code != 0
            and any("공공기관 명칭 날조" in e for e in out.get("errors", []))
            and any("학술논문/학술지 날조" in e for e in out.get("errors", [])),
        ),
        # 6. Historical events: Valid historical events pass
        (
            "historical_events_valid",
            "제1차 갑오개혁 및 동학농민운동 1차 봉기 당시의 기록 분석.",
            lambda out, code: code == 0 and len(out.get("errors", [])) == 0,
        ),
        # 7. Historical events: Fabricated historical rounds, Hanja numerals & single treaties blocked (Section 5.1 #3)
        (
            "historical_events_invalid",
            "제四차 갑오개혁 및 第4次 갑오개혁, 제2차 을사조약, 제2차 을미개혁, 3차 동학농민운동 참조.",
            lambda out, code: code != 0 and any("한국사 사건/조약 날조" in e for e in out.get("errors", [])),
        ),
        # 8. Judicial procedures: Valid procedures pass (including supervisory guidance)
        (
            "judicial_procedures_valid",
            "서울중앙지방검찰청 검사의 약식명령 청구 및 경찰의 구속영장 신청, 대검찰청의 지휘 사실을 기재합니다.",
            lambda out, code: code == 0 and len(out.get("errors", [])) == 0,
        ),
        # 9. Judicial procedures: Impossible procedures with long clauses blocked (Section 5.1 #4)
        (
            "judicial_procedures_invalid",
            "대검찰청 특별수사본부는 이번 사건과 관련하여 피의자들에 대해 약식명령을 청구하였고 경찰은 관할 법원에 직접 영장을 청구하였다.",
            lambda out, code: code != 0 and any("불가능한 사법절차 날조" in e for e in out.get("errors", [])),
        ),
        # 10. Evidence-First & Abstention protocol
        (
            "evidence_first_protocol",
            "<evidence>2026-08-30T10:00:00Z</evidence> [INSUFFICIENT_DATA] 추가 분석 필요.",
            lambda out, code: code == 0 and len(out.get("errors", [])) == 0,
        ),
        # 11. Benign regression: legitimate artifacts must PASS (review-found
        #     false positives — 제44조의2, "재판에 필요", 버전 2.3, 시행예정일)
        (
            "benign_real_articles_pass",
            "정보통신망법 제44조의2 위반 혐의로 기재한다. 이 자료는 재판에 필요하다. "
            "분석 도구 버전 2.3으로 산출하였다. 개정법은 2027-01-01 시행 예정이다. "
            "민법 제2조의2에 따른 신의성실 원칙도 언급한다.",
            lambda out, code: code == 0 and len(out.get("errors", [])) == 0,
        ),
        # 12. Benign regression: checksum-style notes with negated/softened claims
        (
            "benign_negation_pass",
            "해당 행위의 완전한 입증은 어렵다. 유출이 확실시되지 않아 미확인으로 둔다. "
            "100% 확인 불가한 부분은 미측정으로 기록한다. 조작 가능성을 배제할 수 없다.",
            lambda out, code: code == 0 and len(out.get("errors", [])) == 0,
        ),
    ]

    passed_tests = 0
    total_tests = len(tests)
    test_results = {}

    with tempfile.TemporaryDirectory() as td:
        for name, text, checker in tests:
            f = Path(td) / f"{name}.md"
            f.write_text(text, encoding="utf-8")
            s_out = io.StringIO()
            s_err = io.StringIO()
            with redirect_stdout(s_out), redirect_stderr(s_err):
                argv = [str(f), "--json"]
                if name == "evidence_first_protocol":
                    ev_f = Path(td) / f"{name}_ev.json"
                    ev_f.write_text('{"timestamp": "2026-08-30T10:00:00Z"}', encoding="utf-8")
                    argv.extend(["--evidence", str(ev_f)])
                code = _main(argv)
            try:
                out = json.loads(s_out.getvalue())
            except Exception:
                out = {"errors": [s_err.getvalue()]}
            ok = checker(out, code)
            if ok:
                passed_tests += 1
                test_results[name] = {"status": "PASS", "code": code, "errors": out.get("errors", [])}
            else:
                test_results[name] = {"status": "FAIL", "code": code, "errors": out.get("errors", [])}

    score = int((passed_tests / total_tests) * 100)
    return {
        "suite": "Forensic Report Factuality Health Check Suite (Section 5.1 & 7-8)",
        "score": score,
        "max_score": 100,
        "passed": passed_tests,
        "total": total_tests,
        "status": "PASS" if score == 100 else "FAIL",
        "details": test_results,
    }
