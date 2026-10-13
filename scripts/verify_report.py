#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_report.py — 보고서 초안 할루시네이션 검증기
측정값 없이 채워진 결론, 금지 문구, 근거 없는 해시/시각을 차단한다.
Antigravity hard grounding: 부모가 Model pro로 재실행해야 하는 검증.

C2 분리: 정규식/상수 테이블은 report_patterns.py, 스캔·추출·로딩·바인딩·
헬스체크 함수는 report_core.py 로 옮겼다. 이 파일은 CLI 오케스트레이션과
기존 import 표면(extract_timestamps 등)을 유지하는 얇은 래퍼다.

알려진 한계 (docs/GAPS.md):
- 해시 grounding 은 파일 단위 집합 비교다. 해시 A를 파일 B 서술에 붙이는
  '해시-파일 결합 오류'는 잡지 못한다.
- 법령 조문은 korean_law MCP 응답과의 자동 대조가 불가능하다. 출처 표기 없는
  조문 인용을 경고(WARN)로 알릴 뿐이다. 조문 텍스트 자체의 진위는 검증하지 않는다.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from scripts.report_patterns import (
        ABOLISHED_GOV_AGENCIES,
        CURRENT_YEAR,
        EVIDENCE_TAG_RE,
        FABRICATED_ACADEMIC_JOURNALS_RE,
        FABRICATED_AGENCY_RE,
        FABRICATED_HISTORICAL_PATTERNS,
        FUTURE_ACADEMIC_CITATION_RE,
        FUTURE_CONTEXT_RE,
        IMPOSSIBLE_JUDICIAL_PROCEDURE_PATTERNS,
        KOREAN_PARTICLE_SUFFIX,
        KST,
        LAW_CITATION_RE,
        LAW_SOURCE_MARKER_RE,
        PRECEDENT_RE,
        STATUTE_BOUNDS,
        STATUTE_SUBARTICLES,
        VALID_CASE_CODES,
        _make_statute_pattern,
    )
    from scripts.report_core import (
        check_hash_file_binding,
        extract_hashes,
        extract_timestamps,
        load_evidence_hash_file_pairs,
        load_evidence_hashes,
        read_text_smart,
        run_forensic_health_check,
        scan_certainty_variants,
        scan_forbidden,
    )
except ImportError:  # scripts/ 가 sys.path 에 직접 있는 경우
    from report_patterns import (
        ABOLISHED_GOV_AGENCIES,
        CURRENT_YEAR,
        EVIDENCE_TAG_RE,
        FABRICATED_ACADEMIC_JOURNALS_RE,
        FABRICATED_AGENCY_RE,
        FABRICATED_HISTORICAL_PATTERNS,
        FUTURE_ACADEMIC_CITATION_RE,
        FUTURE_CONTEXT_RE,
        IMPOSSIBLE_JUDICIAL_PROCEDURE_PATTERNS,
        KOREAN_PARTICLE_SUFFIX,
        KST,
        LAW_CITATION_RE,
        LAW_SOURCE_MARKER_RE,
        PRECEDENT_RE,
        STATUTE_BOUNDS,
        STATUTE_SUBARTICLES,
        VALID_CASE_CODES,
        _make_statute_pattern,
    )
    from report_core import (
        check_hash_file_binding,
        extract_hashes,
        extract_timestamps,
        load_evidence_hash_file_pairs,
        load_evidence_hashes,
        read_text_smart,
        run_forensic_health_check,
        scan_certainty_variants,
        scan_forbidden,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report hallucination guard — hard grounding verifier")
    parser.add_argument("report", nargs="?", default=None, help="Report draft path (.md/.html)")
    parser.add_argument("--health-check", action="store_true", help="Run Section 5.1 & 7-8 forensic factuality health check suite")
    parser.add_argument("--evidence", nargs="*", default=[], help="Evidence files (audit json, audit_trail.jsonl, timeline json, etc.) for hash grounding")
    parser.add_argument("--timeline", help="Timeline events.json for timestamp grounding (optional)")
    parser.add_argument("--claim-ledger", help="Optional path to claim-ledger.md for Section 6 verification")
    parser.add_argument("--law-cache", help="korean_law MCP 응답 캐시 JSON (법령대조 근거파일, 스켈레톤 — 자동대조 미완성)")
    parser.add_argument("--allow-historical", action="store_true", help="역사적 부처명 인용 허용 (오류 대신 경고 처리)")
    parser.add_argument("--morph-grounding", action="store_true", help="Kiwi 형태소 기반 증거-보고서 용어 일치도 검증 (Section 5.2)")
    parser.add_argument("--high-fidelity", action="store_true", help="Local High-Fidelity gate: require evidence files and <evidence> tags plus morpheme overlap (no Vertex API)")
    parser.add_argument("--json", action="store_true", help="Output JSON result")
    parser.add_argument("--strict", action="store_true", help="Fail with exit 1 if warnings are detected")
    args = parser.parse_args(argv)

    if args.health_check:
        health_report = run_forensic_health_check()
        if args.json:
            print(json.dumps(health_report, ensure_ascii=False, indent=2))
        else:
            print(f"[{health_report['status']}] {health_report['suite']}: {health_report['score']}/{health_report['max_score']} points ({health_report['passed']}/{health_report['total']} passed)")
            for name, d in health_report["details"].items():
                print(f"  - {name}: {d['status']}")
        return 0 if health_report["status"] == "PASS" else 1

    if not args.report:
        parser.print_help()
        return 2

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"[-] Report not found: {report_path}", file=sys.stderr)
        return 2

    text, encoding_used, lossy = read_text_smart(report_path)

    errors = []
    warnings = []
    if lossy:
        warnings.append(f"보고서 인코딩 판별 실패({encoding_used}) — 치환 문자가 있어 검증 누락 가능")

    # 1) 금지 문구 (직후 부정 문맥은 제외)
    forbidden = scan_forbidden(text)
    if forbidden:
        errors.append(f"금지 문구 발견: {sorted(set(forbidden))} — GEMINI 실패폐쇄 위반")

    # 1-1) 과단정 변형 (동의어 우회 방어)
    certainty_variants = scan_certainty_variants(text)
    if certainty_variants:
        errors.append(f"과단정 변형 표현 발견: {certainty_variants[:3]} — 부정/한정 표기로 바꿀 것")

    # 2) 해시 grounding (SHA-256 전체 + MD5/SHA-1 라벨 붙은 값)
    report_hashes = {h.lower() for h in extract_hashes(text)}
    if report_hashes:
        evidence_hashes = load_evidence_hashes(args.evidence)
        if evidence_hashes:
            orphan = report_hashes - evidence_hashes
            if orphan:
                errors.append(f"근거 없는 해시 {len(orphan)}개: {sorted(list(orphan))[:3]} — evidence 파일에 없는 해시를 보고서에 쓰지 말 것")
        elif args.evidence:
            ev_names = ", ".join(Path(p).name for p in args.evidence)
            errors.append(f"해시 {len(report_hashes)}개가 보고서에 있으나 evidence({ev_names})에 해당 해시 없음 — audit_timestamps.py --json 결과 또는 .lazyforensic/audit_trail.jsonl 을 --evidence 로 전달해야 함")
        else:
            # --evidence 가 아예 없으면 grounding 근거 자체가 없다. 과거에는
            # WARN(통과)으로 두어 '감사 생략 + 조작 해시'라는 핵심 위협이
            # 게이트를 통과했다. 실패폐쇄: 근거 없는 해시는 어느 경로로
            # 들어왔든 FAIL이다.
            errors.append(
                f"근거 없는 해시 {len(report_hashes)}개: {sorted(list(report_hashes))[:3]} — "
                "--evidence 미제시로 grounding 불가. 감사 없이 쓴 해시는 조작과 구별할 수 없다. "
                "audit_timestamps.py <원본> --json > audit.json 후 --evidence 로 재검증할 것"
            )

    # 2-1) 해시-파일명 인접성 검증 (Proximity Binding): 정상 해시를 다른
    #      파일 서술에 재사용하는 증거 조작을 차단한다. report_hashes 는
    #      위에서 1회 계산한 것을 재사용한다.
    if report_hashes and args.evidence:
        evidence_pairs = load_evidence_hash_file_pairs(args.evidence)
        for v in check_hash_file_binding(text, evidence_pairs):
            if v.startswith("[SCHEMA-WARN]"):
                warnings.append(v[len("[SCHEMA-WARN] "):])
            else:
                errors.append(v)

    # 3) Chain of Custody 빈칸 검증: 해시 없음 + 결론이 '일치'이면 경고
    if "미측정" not in text and "미확인" not in text:
        if re.search(r"비교 결과[^\n]*일치", text) and not report_hashes:
            warnings.append("해시 없이 '일치' 결론 — '미측정'으로 표기해야 함")

    # 4-0) 타임라인 grounding 없이도 성립하는 절대 검증: 현재 연도(그리고 month/day
    #    정합성)를 초과하는 시각 인용은 그 자체로 날조다. --timeline 유무와 무관하게 FAIL.
    #    단, '시행 예정/계획/예상' 등 미래 문맥은 정상 서술이므로 WARN으로 강등한다.
    #    타임존은 KST로 고정해 실행 머신 TZ과 무관하게 판정한다.
    now = datetime.now(KST)
    future_hits: set[str] = set()
    for line in text.splitlines():
        for ts in extract_timestamps(line):
            ts_date = ts.split(" ")[0]
            try:
                is_future = datetime.strptime(ts_date, "%Y-%m-%d").replace(tzinfo=KST) > now
            except ValueError:
                # 월/일 오기(예: 2024-13-45)도 정합성 오류로 본다
                if ts not in future_hits:
                    future_hits.add(ts)
                    errors.append(f"불가능한 날짜 형식: '{ts}' — 달력에 존재하지 않는 날짜입니다")
                continue
            if not is_future:
                continue
            if FUTURE_CONTEXT_RE.search(line) and ts not in future_hits:
                future_hits.add(ts)
                warnings.append(
                    f"미래 시각({ts})이 예정/시행/계획 문맥에 사용됨 — 사건 서술이 아니라면 문제없으나, 사건 시각으로는 근거 없음"
                )
            elif ts not in future_hits:
                future_hits.add(ts)
                errors.append(
                    f"미래 시각 날조: '{ts}' — 현재({now.strftime('%Y-%m-%d %H:%M')})보다 미래 시점의 사건 서술은 존재할 수 없습니다"
                )

    # 4) 타임라인 grounding (optional): 보고서 내 시각이 timeline에 있는지.
    #    미확인/미측정 표기가 '있는 줄'의 시각은 건너뛴다 (전역 치환 아닌 per-item 판정).
    if args.timeline:
        try:
            tl_text, _, _ = read_text_smart(Path(args.timeline))
            tl_times = set(extract_timestamps(tl_text))
            for line in text.splitlines():
                if "미확인" in line or "미측정" in line:
                    continue
                orphan_times = [t for t in extract_timestamps(line) if t not in tl_times]
                if orphan_times:
                    warnings.append(f"타임라인에 없는 시각 {orphan_times[:3]} — 근거 시각만 사용해야 함")
        except Exception:
            pass

    # 5) 법령 환각: 조문 인용이 있으면 korean_law MCP 출처 표기 요구 (자동 대조 불가 → WARN)
    citations = sorted(set(LAW_CITATION_RE.findall(text)))
    if citations and not LAW_SOURCE_MARKER_RE.search(text):
        preview = ", ".join(citations[:3]) + (f" 외 {len(citations) - 3}" if len(citations) > 3 else "")
        warnings.append(f"조문 인용({preview})이 있으나 korean_law MCP 출처 표기 없음 — MCP 응답과 대조 전까지 미확인으로 둘 것")

    # 5-0) --law-cache 실대조: korean_law MCP 응답캐시(JSON)를 기반으로 조문 실존 여부를 대조한다.
    if args.law_cache:
        try:
            cache_path = Path(args.law_cache)
            cache_text = cache_path.read_text(encoding="utf-8", errors="replace")
            json.loads(cache_text)  # 유효한 JSON 형식 검증
            clean_cache = re.sub(r"\s+", "", cache_text)

            missing_citations = []
            matched_citations = []

            for cit in citations:
                clean_cit = re.sub(r"\s+", "", cit)
                if clean_cit in clean_cache:
                    matched_citations.append(cit)
                    continue

                m = re.search(r"제\s*(\d+)\s*(?:조(?:의\s*(\d+))?)", cit)
                found = False
                if m:
                    art_token = f"제{m.group(1)}조"
                    if m.group(2):
                        art_token += f"의{m.group(2)}"
                    if art_token in clean_cache:
                        found = True
                if found:
                    matched_citations.append(cit)
                else:
                    missing_citations.append(cit)

            if missing_citations:
                missing_str = ", ".join(missing_citations)
                msg = (
                    f"조문 인용({missing_str})이 법령 캐시({cache_path.name})에 존재하지 않음 — "
                    f"원문 대조 전까지 미확인 유지"
                )
                # B2-1: 조건부 FAIL 승격 — strict와 함께일 때만 errors, 기본은 WARN 유지(오탐 방지).
                if getattr(args, "strict", False):
                    errors.append(msg + " — 허위 조문 날조로 차단 (FAIL)")
                else:
                    warnings.append(msg + " (WARN)")
            elif matched_citations:
                # 모든 조문이 캐시와 일치하면 출처 미표기 경고(WARN)를 정상 그라운딩으로 해제
                # 단, --strict에서는 인간 대조를 위해 WARN 유지(오탐 방지).
                if not getattr(args, "strict", False):
                    warnings = [w for w in warnings if not ("조문 인용" in w and "korean_law MCP 출처 표기 없음" in w)]
        except Exception as exc:
            warnings.append(f"법령대조용 MCP 응답캐시 읽기 실패({args.law_cache}): {exc} — 원문 대조 전까지 미확인 유지")

    # 5-1) 법령 조문 상한 경계 검사 (허위 조문 날조 FAIL 차단, 공백 유연성 및 중복 스팬 제거)
    matched_spans: list[tuple[int, int]] = []
    sorted_statutes = sorted(STATUTE_BOUNDS.items(), key=lambda x: len(x[0]), reverse=True)

    for statute, max_art in sorted_statutes:
        pat = _make_statute_pattern(statute)
        for m in pat.finditer(text):
            span = m.span()
            if any(s <= span[0] and span[1] <= e for s, e in matched_spans):
                continue
            matched_spans.append(span)
            art_num = int(m.group(1))
            sub_num = m.group(2)
            full_ref = m.group(0)
            if art_num > max_art or art_num < 1:
                errors.append(
                    f"{statute} 허위 조문 날조 발견: {full_ref} (현행 {statute}은 제1조~제{max_art}조까지만 존재함)"
                )
            elif sub_num is not None:
                max_sub = STATUTE_SUBARTICLES.get(statute, 0)
                if int(sub_num) > max_sub or int(sub_num) < 1:
                    errors.append(
                        f"{statute} 허위 가지번호 날조 발견: {full_ref} "
                        f"(현행 {statute}의 가지번호(제N조의M)는 최대 '의{max_sub}'까지만 존재함)"
                    )

    # 5-2) 판례 연도 검사 (미래 연도 판결 날조 FAIL 차단)
    #    사건부호 판정은 문맥 요건을 충족한 후보만 검사한다: 임의 숫자+한글
    #    조합(예: "2024자연 12345")을 판례로 오탐하는 것을 방지하기 위해
    #    법원명 선행 또는 선고/판결/결정/사건/호 후행 어미를 요구한다.
    for m in PRECEDENT_RE.finditer(text):
        year = int(m.group("year"))
        code = m.group("code")
        num = m.group("num")
        case_str = f"{year}{code}{num}"
        if year > CURRENT_YEAR:
            errors.append(
                f"판례 허위 날조 발견: 미래 연도 판결 인용 {case_str} (현재 {CURRENT_YEAR}년 이후 판결은 존재할 수 없음)"
            )
        elif year < 1948:
            errors.append(
                f"판례 허위 날조 발견: 대한민국 사법부 수립 이전 판결 {case_str} (1948년 이전)"
            )
        if code not in VALID_CASE_CODES:
            warnings.append(
                f"판례 부호 의심: 비표준 사건부호 인용 '{code}' in {case_str} — 대법원 규격 사건부호 여부를 확인하십시오."
            )

    # 5-3) 공공기관 및 수사기관 명칭 날조 검사 (Section 5.1 #2)
    for m in FABRICATED_AGENCY_RE.finditer(text):
        errors.append(f"공공기관 명칭 날조 발견: {m.group('agency')} (Section 5.1 #2 실존하지 않는 수사/포렌식 기관)")

    for agency, (abolish_info, successor) in ABOLISHED_GOV_AGENCIES.items():
        pat = re.compile(rf"(?<![가-힣]){re.escape(agency)}{KOREAN_PARTICLE_SUFFIX}")
        if pat.search(text):
            successor_candidates = [s.strip() for s in re.split(r"또는|/|,", successor) if s.strip()]
            has_successor_annotation = any(cand in text for cand in successor_candidates)
            has_historical_marker = bool(
                re.search(rf"\((?:구|과거)\s*{re.escape(agency)}\)", text)
                or re.search(rf"{re.escape(agency)}\s*\((?:현|현행)", text)
            )

            if has_successor_annotation or has_historical_marker or getattr(args, "allow_historical", False):
                warnings.append(
                    f"정부기관 역사적 구 부처명 인용: '{agency}' ({abolish_info}, 현행 '{successor}' 병기됨/역사적 검토 허용)"
                )
            else:
                errors.append(
                    f"정부기관 명칭 오류/날조 발견: 폐지된 구 부처명 인용 '{agency}' ({abolish_info}, 현행 '{successor}' 명칭 사용 필수) (Section 5.1 위반)"
                )

    # 5-3-2) 한국사 사건 및 조약 날조 검사 (Section 5.1 #3)
    for pat, desc in FABRICATED_HISTORICAL_PATTERNS:
        for m in pat.finditer(text):
            matched_text = m.group("target") if "target" in m.groupdict() else m.group(0)
            errors.append(
                f"한국사 사건/조약 날조 발견: '{matched_text}' — {desc} (Section 5.1 #3 위반)"
            )

    # 5-3-3) 불가능한 사법 절차 날조 검사 (Section 5.1 #4)
    for pat, desc in IMPOSSIBLE_JUDICIAL_PROCEDURE_PATTERNS:
        for m in pat.finditer(text):
            matched_text = m.group("target") if "target" in m.groupdict() else m.group(0)
            errors.append(
                f"불가능한 사법절차 날조 발견: '{matched_text}' — {desc} (Section 5.1 #4 위반)"
            )

    # 5-3-4) 학술 논문 및 저널 날조 검사 (Section 5.1 #3)
    for m in FABRICATED_ACADEMIC_JOURNALS_RE.finditer(text):
        fake_journal = m.group("journal")
        errors.append(
            f"학술논문/학술지 날조 발견: 실존하지 않는 가짜 학술지 '{fake_journal}' (Section 5.1 #3 위반)"
        )
    for m in FUTURE_ACADEMIC_CITATION_RE.finditer(text):
        cite_str = m.group("citation")
        pub_year = int(m.group("year") or m.group("year2"))
        if pub_year > CURRENT_YEAR:
            errors.append(
                f"학술논문/학술지 날조 발견: 미래 연도 학술 논문 '{cite_str}' ({pub_year}년) - 현재 연도({CURRENT_YEAR}년)보다 미래의 학술 출판물은 날조된 환각입니다 (Section 5.1 #3 위반)"
            )

    # 5-4) <evidence> 태그 인용 검증 (Section 3.2 #1 Evidence-First)
    evidence_matches = EVIDENCE_TAG_RE.findall(text)
    if evidence_matches:
        combined_ev_text = ""
        for ep in args.evidence:
            p = Path(ep)
            if p.is_file():
                combined_ev_text += "\n" + p.read_text(encoding="utf-8", errors="replace")

        for quote in evidence_matches:
            q_strip = quote.strip()
            if not q_strip:
                errors.append("<evidence> 태그가 비어 있습니다. 증거 측정값을 채우십시오.")
            elif combined_ev_text:
                clean_q = re.sub(r"\s+", " ", q_strip)
                clean_ev = re.sub(r"\s+", " ", combined_ev_text)
                if clean_q not in clean_ev:
                    errors.append(
                        f"근거 인용 불일치: <evidence> 구절('{q_strip[:25]}...')이 제공된 증거 파일에 존재하지 않습니다."
                    )
            else:
                errors.append(
                    f"근거 인용 검증 불가: <evidence> 구절('{q_strip[:25]}...')이 있으나 "
                    "--evidence 파일이 제공되지 않았거나 비어 있습니다. 증거 파일을 지정하십시오."
                )

    # 5-5) Local High-Fidelity 비파라메트릭 게이트 (Section 4.2; Vertex API 호출 없음)
    if args.high_fidelity:
        if not args.evidence:
            errors.append("[High-Fidelity Grounding 위반] High-Fidelity 검증을 위한 원문/증거(--evidence)가 지정되지 않았습니다.")
        elif not evidence_matches:
            errors.append("[High-Fidelity Grounding 위반] 증거 기반 사실관계를 뒷받침하는 <evidence> 원문 인용 태그가 없습니다.")

    # 5-6) Kiwi 형태소 기반 포렌식 그라운딩 검증 (Section 5.2 & 4.2)
    if (args.morph_grounding or args.high_fidelity) and args.evidence:
        try:
            from scripts.korean_morph_forensic import calculate_forensic_grounding
        except ImportError:
            try:
                from korean_morph_forensic import calculate_forensic_grounding
            except ImportError:
                calculate_forensic_grounding = None

        if calculate_forensic_grounding is not None:
            combined_ev = "\n".join(
                Path(ep).read_text(encoding="utf-8", errors="replace")
                for ep in args.evidence if Path(ep).is_file()
            )
            if combined_ev.strip():
                finding_section_match = re.search(
                    r"(?:^|\n)\s*(?:#{1,4}\s*|\d+[\.\)]\s*|제\s*\d+\s*조?\s*|\b|【|\[)?\s*(?:\d+[\.\)]\s*)?"
                    r"(?:감정\s*결과|감정\s*대상물|분석\s*내용|타임라인\s*분석|상세\s*분석|해시\s*검증|증거\s*분석)\b[^\n]*\n?"
                    r"(.*?)"
                    r"(?=\n#{1,2}\s*(?:종합\s*의견|의견|서명|결론|비고|첨부)|\Z)",
                    text,
                    re.DOTALL,
                )
                eval_target = finding_section_match.group(1) if finding_section_match else text
                clean_rep = re.sub(r"<[^>]+>", " ", eval_target)
                clean_ev = re.sub(r"<[^>]+>", " ", combined_ev)
                thresh = 0.70 if args.high_fidelity else 0.55
                grounding_res = calculate_forensic_grounding(clean_ev, clean_rep, threshold=thresh, filter_procedural=True)
                if not grounding_res["is_grounded"]:
                    msg = (
                        f"포렌식 형태소 그라운딩 미달 ({grounding_res['grounding_score']*100:.1f}% < {int(thresh*100)}%): "
                        f"증거에 없는 추정 용어 다수 {grounding_res['unsupported_terms'][:5]}"
                    )
                    if args.high_fidelity:
                        errors.append(f"[High-Fidelity Grounding 위반] {msg}")
                    else:
                        warnings.append(msg)

    # 5-7) Section 6 Claim Ledger 검증
    if args.claim_ledger:
        try:
            from scripts.verify_claim_ledger import verify_claim_ledger_file
        except ImportError:
            try:
                from verify_claim_ledger import verify_claim_ledger_file
            except ImportError:
                verify_claim_ledger_file = None

        if verify_claim_ledger_file is not None:
            ledger_report = verify_claim_ledger_file(args.claim_ledger, synthesis_path=args.report)
            if not ledger_report["ok"]:
                for v in ledger_report["violations"]:
                    errors.append(f"[Claim Ledger 위반] [{v['claimId']}] {v['violation']}")
        else:
            warnings.append("verify_claim_ledger 모듈을 찾을 수 없어 원장 검증을 건너뛰었습니다.")

    result = {
        "report": str(report_path),
        "encoding": encoding_used,
        "forbidden_hits": sorted(set(forbidden)),
        "report_hashes": sorted(list(report_hashes)),
        "law_citations": citations[:10],
        "errors": errors,
        "warnings": warnings,
        "verdict": "FAIL" if errors else ("WARN" if warnings else "PASS"),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        if errors:
            print(f"[FAIL] 할루시네이션 검증 실패 ({len(errors)} errors, {len(warnings)} warnings)", file=sys.stderr)
            for e in errors:
                print(f"  - ERROR: {e}", file=sys.stderr)
            for w in warnings:
                print(f"  - WARN: {w}", file=sys.stderr)
            print(f"[HINT] 수정 후 재실행: python scripts/verify_report.py {report_path} --evidence audit.json --json", file=sys.stderr)
        elif warnings:
            print(f"[WARN] {len(warnings)} warnings (통과하나 부모가 Model pro로 대조 필요)")
            for w in warnings:
                print(f"  - {w}")
            if args.strict:
                print(f"[FAIL] --strict 모드: 경고가 감지되어 차단합니다.", file=sys.stderr)
        else:
            print("[PASS] 할루시네이션 검증 통과 — 근거 없는 금지 문구/해시 없음")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
