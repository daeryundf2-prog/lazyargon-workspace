#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_timestamps.py
OS-visible MAC timestamps and file hashes.

This script reads os.stat() only. It does not parse NTFS $MFT,
$STANDARD_INFORMATION vs $FILE_NAME, USN Journal, EXIF, MOV mvhd,
Maya headers, or HWP/Office metadata.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


LIMITATIONS = (
    "os.stat() 표면값만 읽는다. $MFT $SI/$FN, Timestomping, "
    "미디어/Maya/Office 내부 메타데이터는 검사하지 않는다. "
    "st_ctime은 Windows에서는 대체로 파일 생성시각이지만 POSIX에서는 inode 메타데이터 변경시각이다."
)


def format_ts(ts, tz):
    if ts is None:
        return "N/A"
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d %H:%M:%S %z")


def compute_hashes(filepath):
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def audit_file(filepath, tz=None, platform_name=None):
    if tz is None:
        tz = datetime.now().astimezone().tzinfo or timezone.utc
    if platform_name is None:
        platform_name = os.name
    if not os.path.exists(filepath):
        return None

    stat = os.stat(filepath)
    c_time = getattr(stat, "st_ctime", None)
    birth_time = getattr(stat, "st_birthtime", None)
    if platform_name == "nt" and birth_time is None:
        birth_time = c_time
    m_time = getattr(stat, "st_mtime", None)
    a_time = getattr(stat, "st_atime", None)

    try:
        md5_hash, sha256_hash = compute_hashes(filepath)
    except OSError as exc:
        md5_hash, sha256_hash = f"Error: {exc}", f"Error: {exc}"

    inverted = False
    inversion_note = "생성시각을 확인할 수 없어 생성>수정 비교를 수행하지 않음"
    if birth_time is not None and m_time is not None and birth_time <= m_time:
        inversion_note = "생성시각 <= 수정시각 (os.stat 표면값 기준)"
    elif birth_time is not None and m_time is not None and birth_time > m_time:
        inverted = True
        diff_sec = birth_time - m_time
        inversion_note = (
            f"생성시간 > 수정시간 (차이 약 {int(diff_sec // 60)}분). "
            "Windows에서 복사/다운로드 시 흔히 나타난다. "
            "이 사실만으로 속성 조작을 단정하지 않는다. "
            "$SI vs $FN 비교는 본 스크립트 범위 밖이다."
        )

    return {
        "file_path": os.path.abspath(filepath),
        "file_name": os.path.basename(filepath),
        "size_bytes": stat.st_size,
        "created_time": format_ts(birth_time, tz),
        "ctime_time": format_ts(c_time, tz),
        "ctime_semantics": (
            "Windows creation time" if platform_name == "nt"
            else "POSIX inode metadata change time; not file creation"
        ),
        "modified_time": format_ts(m_time, tz),
        "accessed_time": format_ts(a_time, tz),
        "timezone": str(tz),
        "created_gt_modified": inverted,
        "analysis_note": inversion_note,
        "md5_legacy": md5_hash,
        "sha256": sha256_hash,
        "limitations": LIMITATIONS,
    }


def print_audit_report(res):
    print("=" * 70)
    print("  파일 타임스탬프 / 해시 점검 (os.stat 한정)")
    print("=" * 70)
    print(f"  파일명       : {res['file_name']}")
    print(f"  전체 경로    : {res['file_path']}")
    print(f"  파일 크기    : {res['size_bytes']:,} Bytes")
    print(f"  표시 타임존  : {res['timezone']}")
    print("-" * 70)
    print(f"  생성 일시     : {res['created_time']}")
    print(f"  OS ctime      : {res['ctime_time']} ({res['ctime_semantics']})")
    print(f"  수정 일시(M) : {res['modified_time']}")
    print(f"  접근 일시(A) : {res['accessed_time']}")
    print("-" * 70)
    print(f"  SHA-256      : {res['sha256']}")
    print(f"  MD5 (legacy) : {res['md5_legacy']}")
    print("-" * 70)
    print(f"  [참고] {res['analysis_note']}")
    print(f"  [한계] {res['limitations']}")
    print("=" * 70)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="OS-visible file timestamps and hashes. Not an $MFT auditor."
    )
    parser.add_argument("file", help="Target file path")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the audit result as JSON (stdout redirect로 audit.json 생성 — "
        "verify_report.py --evidence 의 근거 파일이 된다)",
    )
    args = parser.parse_args(argv)

    res = audit_file(args.file)
    if res is None:
        print(f"[-] File not found: {args.file}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print_audit_report(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
