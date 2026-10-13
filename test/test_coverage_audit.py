"""coverage_audit.mjs — 원문 대조 커버리지 감사 도구의 계약 테스트.

순환 감사 차단의 핵심 불변식:
  1. --source 없이는 절대 실행되지 않는다 (원문 없는 감사 = 순환 감사).
  2. 감사 키는 원문 항목에서만 뽑힌다 (자체 키워드 목록 불가).
  3. 누락 항목을 원문 행으로 정확히 지목하고, 미달 시 exit 1.
  4. 표 헤더는 항목으로 계수하지 않는다.
deepfake-forensic-radar "21/21 전수 일치" 사건(원문 20여 항목 누락, 순환 감사)의 재발 방지.
"""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "scripts" / "coverage_audit.mjs"

SOURCE = """# 딥페이크 생성 모델 원문 (감사 대상)

| 모델 | 개발 | 핵심 매커니즘 |
|---|---|---|
| Wan2.1 | Alibaba | Flow Matching + Video DiT |
| HunyuanVideo | Tencent | Dual-Stream DiT |
| CogVideoX | Zhipu | Expert Transformer DiT |
| Mochi 1 | Genmo | AsymmDiT 비대칭 구조 |
| Sora | OpenAI | 시공간 패치 DiT |

## 음성 복제
- F5-TTS: SWivid Flow Matching 제로샷 복제
- CosyVoice 2: Alibaba 인과 Flow Matching
"""

TARGET_FULL = """# 산출물 (전수 수록본)

- Wan2.1: Alibaba Flow Matching Video DiT 방식
- HunyuanVideo: Tencent Dual-Stream DiT 구조
- CogVideoX: Zhipu Expert Transformer DiT 체계
- Mochi 1: Genmo 비대칭 AsymmDiT 구조
- Sora: OpenAI 시공간 패치 기반 생성

음성: F5-TTS(SWivid Flow Matching 제로샷 복제), CosyVoice 2(Alibaba 인과 Flow Matching) 수록
"""

TARGET_BROKEN = """# 산출물 (결함 재현본 — 2개 누락)

- Wan2.1: Alibaba Flow Matching Video DiT 방식
- HunyuanVideo: Tencent Dual-Stream DiT 구조
- CogVideoX: Zhipu Expert Transformer DiT 체계
- LTX-Video: Lightricks 실시간 렌더링
"""


def run_audit(*args):
    return subprocess.run(
        ["node", str(AUDIT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
        timeout=60,
    )


class CoverageAuditTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.mkdtemp()
        (Path(self.tmp) / "source.md").write_text(SOURCE, encoding="utf-8")
        (Path(self.tmp) / "target_full.md").write_text(TARGET_FULL, encoding="utf-8")
        (Path(self.tmp) / "target_broken.md").write_text(TARGET_BROKEN, encoding="utf-8")

    def source(self):
        return str(Path(self.tmp) / "source.md")

    def test_refuses_without_source(self):
        proc = run_audit("--target", str(Path(self.tmp) / "target_full.md"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("감사 거부", proc.stderr)
        self.assertIn("순환 감사", proc.stderr)

    def test_refuses_with_missing_source_file(self):
        proc = run_audit("--source", str(Path(self.tmp) / "없는파일.md"), "--target", str(Path(self.tmp) / "target_full.md"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("찾을 수 없다", proc.stderr)

    def test_full_coverage_passes_with_mapping_receipt(self):
        receipt_path = Path(self.tmp) / "receipt.json"
        proc = run_audit(
            "--source", self.source(),
            "--target", str(Path(self.tmp) / "target_full.md"),
            "--json", str(receipt_path),
        )
        self.assertEqual(proc.returncode, 0, proc.stdout)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["verdict"], "PASS")
        self.assertEqual(receipt["totalItems"], 7)  # 표 5행 + 불릿 2개 — 헤더 행은 계수하지 않는다
        self.assertEqual(receipt["missingItems"], 0)
        self.assertEqual(receipt["source"]["sha256"], __import__("hashlib").sha256(Path(self.source()).read_bytes()).hexdigest())
        # 매핑 수신증: 항목별로 원문 행이 기록되어 있다 (헤더 3행·구분자 4행 제외)
        lines = {item["sourceLine"] for item in receipt["perItem"]}
        self.assertIn(5, lines)  # Wan2.1 표 행
        self.assertNotIn(3, lines)  # 표 헤더는 항목이 아니다
        for item in receipt["perItem"]:
            self.assertTrue(item["evidence"], f"L{item['sourceLine']} 항목에 증거가 없다")

    def test_missing_items_fail_with_precise_line_blame(self):
        receipt_path = Path(self.tmp) / "receipt.json"
        proc = run_audit(
            "--source", self.source(),
            "--target", str(Path(self.tmp) / "target_broken.md"),
            "--json", str(receipt_path),
        )
        self.assertEqual(proc.returncode, 1)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(receipt["verdict"], "FAIL")
        missing_lines = {item["sourceLine"] for item in receipt["missing"]}
        # Sora(L9)와 Mochi(L8)가 정확히 누락으로 지목되어야 한다 —
        # 산출물 제목에 모델명이 등장해도 강한 키 규칙이 오매칭을 막는다
        self.assertEqual(missing_lines, {8, 9})
        joined_excerpts = (receipt["missing"][0]["excerpt"] + receipt["missing"][1]["excerpt"]).lower()
        self.assertIn("mochi", joined_excerpts)
        self.assertIn("sora", joined_excerpts)

    def test_min_threshold_relaxation(self):
        proc = run_audit(
            "--source", self.source(),
            "--target", str(Path(self.tmp) / "target_broken.md"),
            "--min", "0.5",
        )
        self.assertEqual(proc.returncode, 0)

    def test_table_header_row_is_not_an_item(self):
        # 원문에 표만 있어도 헤더는 항목이 아니다 — 헤더만 있는 표는 레코드 0개로 감사 거부
        header_only = Path(self.tmp) / "header_only.md"
        header_only.write_text("| 모델 | 개발 |\n|---|---|\n", encoding="utf-8")
        proc = run_audit("--source", str(header_only), "--target", str(Path(self.tmp) / "target_full.md"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("하나도 추출하지 못했다", proc.stderr)


if __name__ == "__main__":
    unittest.main()
