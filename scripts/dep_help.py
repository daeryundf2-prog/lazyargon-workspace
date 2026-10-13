#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dep_help.py — 선택 의존성 미설치 시 일관된 설치 안내

모든 스크립트가 같은 형식으로 "무엇을·왜·어떻게 깔지"를 알려주도록 한다.
설치 위치는 install.sh가 실제로 쓰는 경로(시스템 pip 또는 .venv)를 기준으로 안내한다.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# 모듈명 → (pip 패키지명, 이걸 깔면 되는 기능)
DEP_MAP = {
    "fitz": ("pymupdf", "PDF 표찰/병합/텍스트 추출"),
    "olefile": ("olefile", "구형 HWP 5.0 바이너리 읽기"),
    "pypdf": ("pypdf", "PDF 텍스트 추출 (pymupdf 대체)"),
    "openpyxl": ("openpyxl", "XLSX 거래내역 읽기"),
    "kiwipiepy": ("kiwipiepy", "한국어 형태소 그라운딩(정확도 상승)"),
    "anydoc": ("firecrawl-anydoc", "Office 문서 → Markdown 변환"),
    "hwp_hwpx_parser": ("hwp-hwpx-parser", "HWP 5.0 정확한 파싱"),
}


def _venv_python() -> str | None:
    """install.sh/.ps1이 만든 .venv python 경로 (있을 때만)."""
    root = Path(__file__).resolve().parent.parent
    for cand in (root / ".venv" / "bin" / "python",
                 root / ".venv" / "Scripts" / "python.exe"):
        if cand.is_file():
            return str(cand)
    return None


def install_hint(module: str) -> str:
    pkg, feature = DEP_MAP.get(module, (module, ""))
    venv_py = _venv_python()
    if venv_py:
        cmd = f'"{venv_py}" -m pip install {pkg}'
    else:
        cmd = f"pip install {pkg}"
    tail = f" — {feature}에 필요" if feature else ""
    return (f"[!] 필요한 패키지가 없습니다: {module}{tail}\n"
            f"    설치: {cmd}\n"
            f"    (또는 install.sh / install.ps1 재실행)")


def require(module: str):
    """모듈이 있으면 True, 없으면 안내 후 SystemExit(3)."""
    if importlib.util.find_spec(module) is not None:
        return True
    print(install_hint(module), file=sys.stderr)
    raise SystemExit(3)
