#!/bin/sh
# bootstrap.sh — 새 컴퓨터에서 lazyforensic 세팅 (clone 직후 한 번 실행)
#
#   git clone https://github.com/daeryundf2-prog/lazyforensic.git
#   cd lazyforensic && sh bootstrap.sh            # 전체 의존성 설치
#   sh bootstrap.sh --check                       # 현재 환경 진단만
#   sh bootstrap.sh --with imaging stt            # 특정 그룹만
#
# 이 스크립트가 하는 일:
#   1. python3 존재 확인
#   2. ~/.lfenv 가상환경 생성 + 선택 의존성(pillow/faster-whisper/sherlock/kiwipiepy) 설치
#   3. bin/을 PATH에 추가하는 한 줄 안내
#   4. pip으로 못 까는 바이너리(ffmpeg/fpcalc 등)는 설치 명령만 안내
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3가 없습니다. python.org 또는 OS 패키지 관리자로 3.10+ 설치 후 재시도하세요." >&2
  exit 2
fi

python3 "$ROOT/scripts/setup_forensic_env.py" "$@"

cat <<EOF

---
PATH 추가 (한 번만, 셸 설정 파일에):
  export PATH="$ROOT/bin:\$PATH"
그 뒤 어디서든:  lazyforensic scan <폴더>
EOF
