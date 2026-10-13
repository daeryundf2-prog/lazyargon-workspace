"""test_hwp5_fixture.py — 합성(익명화) HWP 5.0 OLE 픽스처 회귀 테스트.

실제 사용자 문서를 커밋하지 않고, 테스트 시점에 최소 OLE Compound File을
합성한다. 구조는 HWP 5.0의 본질만 재현한다:

  CFB 저장소 → "BodyText" 스토리지 → "Section0" 스트림
  스트림 = raw-deflate 압축된 [레코드 헤더 + UTF-16LE 본문]

이 경로는 parse_hwp_legacy의 olefile 폴백이 읽는 실제 경로이며,
hwp_hwpx_parser가 있으면 1차 경로가 먼저 시도된다(두 경로 모두 검증).
"""
import struct
import sys
import zlib
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import parse_korean_doc as pkd  # noqa: E402

SENTINEL = "피고인 김철수는 2024년 3월 15일 계약을 체결하였다."
SECTOR = 512
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
FATSECT = 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


def _dir_entry(name: str, obj_type: int, child: int, start: int, size: int) -> bytes:
    name_utf16 = name.encode("utf-16-le") + b"\x00\x00"
    entry = name_utf16.ljust(64, b"\x00")
    entry += struct.pack("<H", len(name_utf16))      # name_len (bytes incl null)
    entry += struct.pack("<B", obj_type)              # 0=free 1=storage 2=stream 5=root
    entry += struct.pack("<B", 1)                     # color: black
    entry += struct.pack("<III", NOSTREAM, NOSTREAM, child)  # left, right, child
    entry += b"\x00" * 16                             # CLSID
    entry += struct.pack("<I", 0)                     # state bits
    entry += struct.pack("<Q", 0) * 2                 # creation + modified time
    entry += struct.pack("<I", start)                 # start sector
    entry += struct.pack("<Q", size)                  # stream size
    assert len(entry) == 128
    return entry


def build_hwp5(text: str) -> bytes:
    """최소 OLE2 Compound File을 합성해 HWP 5.0 바이너리를 만든다."""
    # BodyText/Section0 페이로드: HWPTAG_PARA_TEXT(67) 레코드 + UTF-16LE 본문
    body = text.encode("utf-16-le")
    record = struct.pack("<I", 67 | (len(body) << 20)) + body  # tag67, level0, size<4096
    compressed = zlib.compressobj(9, zlib.DEFLATED, -15)
    payload = compressed.compress(record) + compressed.flush()
    # 미니 스트림 컷오프(4096) 이상이어야 일반 섹터에 저장된다 — 뒷바이트는
    # zlib.decompress가 무시하므로 0 패딩.
    payload = payload.ljust(4096, b"\x00")
    n_data = (len(payload) + SECTOR - 1) // SECTOR
    payload = payload.ljust(n_data * SECTOR, b"\x00")

    fat = [FREESECT] * 128
    fat[0] = FATSECT                       # sector 0 = FAT 자신
    fat[1] = ENDOFCHAIN                    # sector 1 = 디렉터리
    for i in range(n_data):                # sector 2.. = Section0 데이터 체인
        fat[2 + i] = ENDOFCHAIN if i == n_data - 1 else 3 + i
    fat_sector = struct.pack("<128I", *fat)

    directory = b"".join([
        _dir_entry("Root Entry", 5, 1, ENDOFCHAIN, 0),
        _dir_entry("BodyText", 1, 2, ENDOFCHAIN, 0),
        _dir_entry("Section0", 2, NOSTREAM, 2, n_data * SECTOR),
        bytes(128),                        # free entry padding
    ])

    header = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # CFB signature
    header += b"\x00" * 16                          # CLSID
    header += struct.pack("<HHHH", 0x003E, 3, 0xFFFE, 9)   # minor, major, byteorder, sector shift
    header += struct.pack("<H", 6)                  # mini sector shift
    header += b"\x00" * 6                           # reserved
    header += struct.pack("<IIIII", 0, 1, 1, 0, 4096)      # ndir(0), nfat, dir start, txn, mini cutoff
    header += struct.pack("<IIII", ENDOFCHAIN, 0, ENDOFCHAIN, 0)  # miniFAT/DIFAT 없음
    header += struct.pack("<109I", 0, *([FREESECT] * 108))         # DIFAT: FAT는 sector 0
    assert len(header) == SECTOR

    return header + fat_sector + directory + payload


@pytest.fixture()
def hwp5_file(tmp_path):
    path = tmp_path / "anonymized_sample.hwp"
    path.write_bytes(build_hwp5(SENTINEL))
    return str(path)


def test_synthetic_hwp5_is_valid_ole(hwp5_file):
    olefile = pytest.importorskip("olefile")
    ole = olefile.OleFileIO(hwp5_file)
    paths = ["/".join(s) for s in ole.listdir()]
    ole.close()
    assert "BodyText/Section0" in paths


def test_parse_hwp5_ole_fallback_extracts_text(hwp5_file, monkeypatch):
    pytest.importorskip("olefile")
    # hwp_hwpx_parser 부재 환경을 강제해 OLE 폴백 경로를 결정적으로 검증한다.
    monkeypatch.setitem(sys.modules, "hwp_hwpx_parser", None)
    result = pkd.parse_hwp_legacy(hwp5_file)
    assert "error" not in result
    assert result["format"] == "HWP 5.0 (OLE Fallback)"
    assert SENTINEL in result["text"]
    assert result["metadata"]["quality"].startswith("rough")


def test_parse_hwp5_primary_or_fallback_no_error(hwp5_file):
    """설치된 의존성 그대로 실행 — 어느 경로든 오류 없이 텍스트를 낸다."""
    result = pkd.parse_hwp_legacy(hwp5_file)
    assert "error" not in result
    assert result["format"].startswith("HWP 5.0")
    if result["format"] == "HWP 5.0 (OLE Fallback)":
        assert SENTINEL in result["text"]
    else:  # hwp-hwpx-parser 경로 — 레코드 구조를 인식하면 본문이 나온다
        assert isinstance(result["text"], str)


def test_hwp5_cli_strict_rejects_rough(hwp5_file):
    """--strict는 rough 품질을 exit 2로 거부한다(폴백 경로 기준)."""
    pytest.importorskip("olefile")
    import subprocess
    script = SCRIPT_DIR / "parse_korean_doc.py"
    cmd = [
        sys.executable,
        "-c",
        "import sys, runpy; sys.modules['hwp_hwpx_parser'] = None; sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')",
        str(script),
        hwp5_file,
        "--strict",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={**__import__("os").environ, "PYTHONUTF8": "1"},
    )
    assert proc.returncode == 2
    assert "rough" in proc.stderr
