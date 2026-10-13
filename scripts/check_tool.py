#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_tool.py — BYO(binary) 게이트 메커니즘

dfir-evtx-hunter / forensic-mft-parser / memory-triage 의 "도구 없으면 결과를
만들지 않는다" 규칙을 글(prose)이 아니라 실행으로 검증한다. 스킬 지시에 따라
분석 명령을 만들기 전에 호출한다.

사용:
    python scripts/check_tool.py hayabusa.exe chainsaw.exe
    python scripts/check_tool.py --python-module dissect

exit 0 = 전부 발견 (분석 진행 가능)
exit 2 = 하나 이상 미발견 (분석 생성 금지 — 설치 안내만 출력)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys



if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
def find_executable(name: str) -> str | None:
    """PATH 에서 실행 파일을 찾는다. .exe 접미사 없이 Windows 도구명을 줘도 시도한다."""
    candidates = [name]
    stem, ext = os.path.splitext(name)
    if not ext and os.name == "nt":
        candidates = [f"{name}.exe", name]
    elif ext.lower() == ".exe" and os.name != "nt":
        candidates = [stem, name]
    for cand in candidates:
        found = shutil.which(cand)
        if found:
            return found
    return None


def find_python_module(module: str) -> str | None:
    try:
        __import__(module)
        return module
    except ImportError:
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="BYO tool existence gate — fail-closed")
    parser.add_argument("tools", nargs="*", help="실행 파일 이름 (hayabusa.exe, MFTECmd.exe, ...)")
    parser.add_argument("--python-module", action="append", default=[],
                        help="임포트 가능한 파이썬 모듈 (dissect 등) — 여러 번 지정 가능")
    args = parser.parse_args(argv)

    if not args.tools and not args.python_module:
        parser.error("최소 하나의 도구 또는 --python-module 이 필요하다")

    found: list[tuple[str, str]] = []
    missing: list[str] = []
    for name in args.tools:
        path = find_executable(name)
        if path:
            found.append((name, path))
        else:
            missing.append(name)
    for mod in args.python_module:
        if find_python_module(mod):
            found.append((f"python:{mod}", "imported"))
        else:
            missing.append(f"python:{mod}")

    for name, path in found:
        print(f"[+] {name}: {path}")
    for name in missing:
        print(f"[-] {name}: NOT FOUND", file=sys.stderr)

    if missing:
        print(
            "[GATE] 도구가 없는 상태에서 분석 결과를 생성하지 않는다 (fail-closed). "
            "설치 안내만 제공하고 종료할 것.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
