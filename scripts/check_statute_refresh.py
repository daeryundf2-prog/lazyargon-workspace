#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_statute_refresh.py — statute_bounds.json 버전·상한 출력 + 수동 대조 체크리스트 (외부망 호출 없음)."""
import json
import sys
from pathlib import Path

def main() -> int:
    root = Path(__file__).resolve().parent.parent
    p = root / "data" / "statute_bounds.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[FAIL] statute_bounds.json 읽기 실패: {exc}", file=sys.stderr)
        return 1
    print(f"version: {data.get('version', 'unknown')}")
    bounds = data.get("bounds", {}) if isinstance(data, dict) else {}
    print(f"entries: {len(bounds)}")
    for name in sorted(bounds):
        print(f"  - {name}: 제{bounds[name]}조 상한")
    print("수동 대조 체크리스트 (외부망 호출 없음, law.go.kr에서 직접 확인):")
    print("  [ ] 1. 버전(YYYY.MM)이 6개월 이내인지 확인")
    print("  [ ] 2. 개정법률 관보에서 상한 조문 변경 여부 대조")
    print("  [ ] 3. 가지번호 상한(statute_subarticles.json)과 함께 갱신")
    print("  [ ] 4. 갱신 후 verify_legal_factuality.py --health-check 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
