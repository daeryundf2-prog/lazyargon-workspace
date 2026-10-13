#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_forensic_env.py — 다른 컴퓨터에서 lazyforensic 선택 도구 환경 복제

핵심 스크립트는 표준 라이브러리만 쓰므로 그대로 동작한다.
이 스크립트는 '선택 의존성' 레이어를 복제한다 — Pillow(이미지/EXIF),
faster-whisper(로컬 STT), sherlock(OSINT) 등.

사용:
    python scripts/setup_forensic_env.py --check          # 뭐가 있는지만 확인
    python scripts/setup_forensic_env.py                  # 가상환경 생성 + 설치
    python scripts/setup_forensic_env.py --dir ~/.lfenv   # 설치 위치 지정
    python scripts/setup_forensic_env.py --with sherlock  # 특정 그룹만

설치 후에는 해당 venv의 python으로 스크립트를 실행한다:
    ~/.lfenv/bin/python scripts/local_stt.py audio/

알려진 한계:
- ffmpeg·whisper.cpp 같은 시스템 바이너리는 pip으로 못 깐다 — 플랫폼별
  명령을 안내로 출력할 뿐 자동 설치하지 않는다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import venv
from pathlib import Path

# 그룹: (표시이름, pip 패키지들, 설치 후 쓸 스크립트)
DEP_GROUPS = {
    "imaging": ("이미지 유사도·EXIF", ["pillow>=10.0,<12", "numpy>=1.26,<3"],
                ["image_similarity.py", "exif_audit.py"]),
    "stt": ("로컬 STT", ["faster-whisper>=1.1,<2"], ["local_stt.py"]),
    "osint": ("사용자명 OSINT", ["sherlock-project"], ["osint_username.py"]),
    "morph": ("한국어 형태소 그라운딩", ["kiwipiepy>=0.20,<1"], ["korean_morph_forensic.py"]),
}

# pip로 못 까는 시스템 바이너리 안내
BINARY_HINTS = {
    "ffmpeg": {"darwin": "brew install ffmpeg", "win32": "winget install Gyan.FFmpeg",
               "linux": "apt install ffmpeg"},
    "fpcalc": {"darwin": "brew install chromaprint", "win32": "winget install chromaprint",
               "linux": "apt install libchromaprint-tools"},
    "sherlock": {"any": "pip install sherlock-project (또는 이 스크립트의 osint 그룹)"},
    "whisper-cli": {"any": "github.com/ggml-org/whisper.cpp 빌드"},
    "transcribe-cli": {"any": "github.com/igitenv/transcribe.cpp 빌드"},
}

# 바이너리 → 활성화되는 스크립트
BINARY_FEATURES = {
    "ffmpeg": ["video_fingerprint.py", "video_integrity.py", "audio_survey.py(비WAV)"],
    "ffprobe": ["video_integrity.py", "audio_survey.py(비WAV)"],
    "fpcalc": ["audio_fingerprint.py"],
    "whisper-cli": ["local_stt.py(whisper.cpp 엔진)"],
    "transcribe-cli": ["local_stt.py(transcribe.cpp 엔진)"],
    "sherlock": ["osint_username.py"],
}


def check_environment() -> dict:
    """현재 python 환경에서 무엇이 가능한지 진단한다."""
    mods = {}
    for name in ("PIL", "numpy", "faster_whisper", "whisper", "sherlock_project",
                 "kiwipiepy", "dissect"):
        mods[name] = importlib.util.find_spec(name) is not None
    bins = {b: bool(shutil.which(b))
            for b in ("ffmpeg", "ffprobe", "fpcalc", "whisper-cli",
                      "transcribe-cli", "sherlock")}
    return {"python": sys.version.split()[0], "modules": mods, "binaries": bins}


def print_check(info: dict) -> None:
    print(f"python {info['python']}")
    for name, ok in info["modules"].items():
        print(f"  {'✅' if ok else '❌'} module {name}")
    for name, ok in info["binaries"].items():
        feats = ", ".join(BINARY_FEATURES.get(name, []))
        tail = f"  → {feats}" if feats else ""
        print(f"  {'✅' if ok else '❌'} binary {name}{tail}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="lazyforensic 선택 의존성 환경 복제")
    ap.add_argument("--check", action="store_true", help="현재 환경 진단만")
    ap.add_argument("--dir", default="~/.lfenv", help="venv 생성 위치 (기본 ~/.lfenv)")
    ap.add_argument("--with", dest="groups", nargs="+",
                    choices=list(DEP_GROUPS), default=None,
                    help="설치할 그룹만 지정 (기본: 전부)")
    ap.add_argument("--json", action="store_true", help="JSON 출력 (--check 전용)")
    args = ap.parse_args(argv)

    if args.check:
        info = check_environment()
        if args.json:
            print(json.dumps(info, ensure_ascii=False, indent=2))
        else:
            print_check(info)
        return 0

    env_dir = Path(args.dir).expanduser()
    groups = args.groups or list(DEP_GROUPS)
    packages = [pkg for g in groups for pkg in DEP_GROUPS[g][1]]

    print(f"venv 생성: {env_dir}")
    try:
        venv.create(env_dir, with_pip=True)
    except Exception as e:
        # python3-venv 미설치(Debian/Ubuntu)나 권한 문제에서 traceback 대신 안내
        print(f"venv 생성 실패: {e}", file=sys.stderr)
        print("Debian/Ubuntu: sudo apt install python3-venv", file=sys.stderr)
        print("macOS: xcode-select --install 또는 python.org 설치본 사용",
              file=sys.stderr)
        return 1
    pip = env_dir / ("Scripts/pip" if sys.platform == "win32" else "bin/pip")

    print(f"설치: {', '.join(packages)}")
    proc = subprocess.run([str(pip), "install", *packages],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        print(f"설치 실패:\n{proc.stderr[-2000:]}", file=sys.stderr)
        return 1

    py = env_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    print(f"\n완료. 이 python으로 실행하세요:\n  {py} scripts/local_stt.py ...")
    print("참고: bin/lazyforensic은 ~/.lfenv/bin/python을 자동으로 우선 사용합니다.")

    # 시스템 바이너리 안내
    missing = [b for b in BINARY_HINTS if not shutil.which(b)]
    if missing:
        print("\n시스템 바이너리가 없습니다 (수동 설치 필요):")
        for b in missing:
            hint = BINARY_HINTS.get(b, {}).get(sys.platform) or \
                BINARY_HINTS.get(b, {}).get("any", "")
            feats = ", ".join(BINARY_FEATURES.get(b, []))
            print(f"  {b}: {hint}" + (f"   → 활성화: {feats}" if feats else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
