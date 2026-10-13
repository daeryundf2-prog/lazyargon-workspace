"""레포 전체 통합 불변식 — 스킬 추가/수정 시 반드시 유지되어야 하는 계약.

deepfake-forensic-radar 사후 검증(2026-08-30)에서 드러난 결함 클래스의 재발 방지:
  1. 라우팅 누락      — 스킬 디렉터리는 만들었지만 GEMINI.md 호스트 계약에 등록하지 않음
  2. 문서-구현 드리프트 — SKILL.md 실행 레시피에 문서화한 CLI 플래그가 스크립트에 없음 (--plot-fft 사례)
  3. 콘텐츠 스트리핑  — 생성 파이프라인이 빈 링크 [](...), 빈 불릿 "-  : " 을 남김
  4. 레인 카운트 드리프트 — "Forensic (13)" 헤더와 실제 표 행 수 불일치

unittest.TestCase 로 작성 — `python -m unittest discover` (CI) 와 pytest 양쪽에서 수집된다.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

# 라우팅 문서에 등록하지 않기로 명시한 예외 (이유 필수)
ROUTING_EXEMPTIONS = {
    # "skill-name": "이유"
}


def skill_dirs():
    return sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))


def read(p):
    return p.read_text(encoding="utf-8")


class RoutingInvariants(unittest.TestCase):
    def test_every_skill_is_routed_in_host_contract(self):
        gemini = read(ROOT / "GEMINI.md")
        for skill_dir in skill_dirs():
            name = skill_dir.name
            if name in ROUTING_EXEMPTIONS:
                continue
            self.assertIn(
                f"skills/{name}/SKILL.md",
                gemini,
                f"스킬 '{name}' 이(가) GEMINI.md 라우팅 테이블에 없다 — 호스트가 이 스킬로 라우팅하지 못한다",
            )

    def test_every_routed_skill_path_exists(self):
        gemini = read(ROOT / "GEMINI.md")
        for match in re.finditer(r"skills/([a-z0-9-]+)/SKILL\.md", gemini):
            self.assertTrue(
                (SKILLS / match.group(1) / "SKILL.md").exists(),
                f"GEMINI.md 이 {match.group(0)} 을(를) 참조하지만 파일이 없다",
            )

    def test_forensic_lane_count_matches_table_rows(self):
        gemini = read(ROOT / "GEMINI.md")
        m = re.search(r"### Forensic \((\d+)[^)]*\)(.*?)(?=\n### |\Z)", gemini, re.DOTALL)
        self.assertIsNotNone(m, "GEMINI.md에 '### Forensic (N ...)' 레인 헤더가 없다")
        declared = int(m.group(1))
        body = m.group(2)
        rows = re.findall(r"^\|\s*[^|]+\|\s*`skills/", body, re.MULTILINE)
        self.assertEqual(
            len(rows),
            declared,
            f"Forensic 레인 헤더는 {declared}개라 선언했지만 표 행은 {len(rows)}개다 — 스킬 추가 시 헤더 수를 함께 갱신할 것",
        )


class DocsContractInvariants(unittest.TestCase):
    """SKILL.md / USER_GUIDE에 문서화된 python 명령이 실제 존재하고 플래그가 등록되어 있는지 검증."""

    PY_INVOCATION_RE = re.compile(r"(?:^|(?:^|\s)(?:uv run\s+)?(?:python3?|py -3)\s+)([^\s`<>|;&]+\.py)([^\n`]*)", re.MULTILINE)
    FLAG_RE = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]+)")

    def documented_commands(self):
        docs = sorted(SKILLS.glob("*/SKILL.md"))
        extra = [ROOT / "README.md", ROOT / "docs" / "USER_GUIDE.md"]
        for p in extra:
            if p.exists():
                docs.append(p)
        for doc in docs:
            content = read(doc)
            for block in re.findall(r"```(?:bash|sh|shell|console)?\n(.*?)```", content, re.DOTALL):
                for line in block.splitlines():
                    line = line.lstrip("$ ").strip()
                    if line.startswith("#") or not line:
                        continue
                    m = re.search(r"(?:^|\s)(?:uv run\s+)?(?:python3?|py -3)\s+([^\s`<>|;&]+\.py)(.*)", line)
                    if m:
                        yield doc, m.group(1), m.group(2)

    def test_documented_scripts_exist(self):
        missing = []
        for doc, script, _ in self.documented_commands():
            candidates = [ROOT / script, doc.parent / script, doc.parent.parent / script]
            if script.startswith(("skills/", "scripts/", "test/")):
                candidates = [ROOT / script]
            if not any(c.exists() for c in candidates):
                missing.append(f"{doc.relative_to(ROOT)}: {script}")
        self.assertEqual(
            missing,
            [],
            "문서화된 python 스크립트가 존재하지 않는다 (문서-구현 드리프트): " + "; ".join(missing),
        )

    def test_documented_flags_are_registered(self):
        drift = []
        for doc, script, argline in self.documented_commands():
            flags = self.FLAG_RE.findall(argline)
            if not flags:
                continue
            candidates = [ROOT / script, doc.parent / script, doc.parent.parent / script]
            source = next((c for c in candidates if c.exists()), None)
            if source is None:
                continue  # 존재 검사는 위 테스트가 담당
            text = read(source)
            for flag in flags:
                # add_argument 등록 또는 수동 argv 파싱 어디든 문자열이 있으면 인정
                if flag not in text:
                    drift.append(f"{doc.relative_to(ROOT)}: {script} {flag}")
        self.assertEqual(
            drift,
            [],
            "문서화된 CLI 플래그가 스크립트에 없다 (--plot-fft 사례의 재발): " + "; ".join(drift),
        )


class MarkdownIntegrityInvariants(unittest.TestCase):
    """생성 파이프라인 스트리핑 흔적 — skills 트리 전체에서 고신뢰 시그니처만 검사한다.

    참고: "빈 강조 ** **" 는 검사 대상에서 뺐다 — `****` 는 통계 유의도 별표와
    PII 마스킹 표기와 같은 바이트 시퀀스라 오탐이 지배한다 (guard 스크립트 주석 참조).
    """

    EMPTY_LINK = re.compile(r"\[\s*\]\(")
    EMPTY_BULLET_COLON = re.compile(r"^[ \t]*[-*+][ \t]+:[ \t]", re.MULTILINE)

    def test_skills_tree_has_no_stripped_markdown(self):
        offenders = []
        for md in sorted(SKILLS.rglob("*.md")):
            content = read(md)
            rel = md.relative_to(ROOT)
            # 인라인 코드 스팬 내용은 패턴 자체를 문서가 인용하는 경우가 있어 제외
            prose = re.sub(r"`[^`\n]*`", "·", content)
            if self.EMPTY_LINK.search(prose):
                offenders.append(f"{rel}: 빈 링크 [](...)")
            if self.EMPTY_BULLET_COLON.search(content):
                offenders.append(f"{rel}: 빈 불릿 '-  : '")
        self.assertEqual(offenders, [], "스트리핑 흔적 발견 (node scripts/markdown_structure_guard.mjs --check 로 전체 진단 가능): " + "; ".join(offenders))

    def test_gaps_doc_lists_implementation_honesty(self):
        # 정직 선언 문서(GAPS.md)가 존재하고, 구현-광고 차이를 추적한다
        gaps = ROOT / "docs" / "GAPS.md"
        self.assertTrue(gaps.exists(), "docs/GAPS.md 가 없다 — 광고-구현 차이 고정 문서가 유지되어야 한다")


if __name__ == "__main__":
    unittest.main()
