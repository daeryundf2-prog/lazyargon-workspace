"""B2-1 오탐 방지: --law-cache 조건부 FAIL 승격 회귀 테스트.

- strict + 캐시미존재(조문번호 없음) -> FAIL (errors 편입)
- strict + 캐시존재(조문번호 있음) -> WARN 유지 (errors 승격 없음)
- 기본(strict 없음) + 캐시미존재 -> WARN (errors 편입 없음)

상한 위반(예: 개인정보보호법 제999조)과 무관한 범위 내 조문(제70조/제32조의2)으로
법령 캐시 판정만 격리 검증한다.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run_verify(report_text: str, cache_data: dict, extra_args: list[str]):
    tmpdir = tempfile.TemporaryDirectory()
    tmp = Path(tmpdir.name)
    # TemporaryDirectory lifetime: keep ref via function attr
    cache_file = tmp / "law_cache.json"
    cache_file.write_text(json.dumps(cache_data, ensure_ascii=False), encoding="utf-8")
    report = tmp / "report.md"
    report.write_text(report_text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_report.py"), str(report),
         "--law-cache", str(cache_file), "--json", *extra_args],
        capture_output=True, text=True, encoding="utf-8",
    )
    data = json.loads(proc.stdout)
    # attach cleanup
    proc._tmpdir = tmpdir  # noqa: SLF001 - keep temp alive until caller done
    return proc, data, tmpdir


CACHE = {"statute": "개인정보보호법", "articles": ["제32조의2", "제71조"]}


class LawCacheBindingTests(unittest.TestCase):
    def test_strict_missing_escalates_to_fail(self):
        # strict + 캐시없음(제70조는 상한 76 이내이나 캐시에 없음) -> FAIL
        proc, data, _td = run_verify(
            "개인정보보호법 제70조 위반이다.\n", CACHE, ["--strict"],
        )
        try:
            self.assertEqual(proc.returncode, 1)
            self.assertEqual(data["verdict"], "FAIL")
            self.assertTrue(
                any("법령 캐시" in e and "존재하지 않음" in e for e in data.get("errors", [])),
                f"errors missing law-cache FAIL: {data}",
            )
        finally:
            _td.cleanup()

    def test_strict_present_stays_warn(self):
        # strict + 캐시있음(제32조의2는 캐시에 있음) -> WARN 유지, errors 승격 없음
        proc, data, _td = run_verify(
            "개인정보보호법 제32조의2 위반이다.\n", CACHE, ["--strict"],
        )
        try:
            self.assertEqual(data["verdict"], "WARN", f"expected WARN, got: {data}")
            self.assertFalse(
                any("법령 캐시" in e for e in data.get("errors", [])),
                f"law-cache must not escalate to errors when present: {data}",
            )
            self.assertEqual(proc.returncode, 1)  # --strict는 WARN이어도 exit 1
        finally:
            _td.cleanup()

    def test_default_missing_stays_warn(self):
        # 기본(strict 없음) + 캐시없음 -> WARN, errors 편입 없음
        proc, data, _td = run_verify(
            "개인정보보호법 제70조 위반이다.\n", CACHE, [],
        )
        try:
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(data["verdict"], "WARN", f"expected WARN, got: {data}")
            self.assertTrue(
                any("법령 캐시" in w and "존재하지 않음" in w for w in data.get("warnings", [])),
                f"warnings missing law-cache WARN: {data}",
            )
            self.assertFalse(
                any("법령 캐시" in e for e in data.get("errors", [])),
                f"law-cache must stay WARN without --strict: {data}",
            )
        finally:
            _td.cleanup()


if __name__ == "__main__":
    unittest.main()
