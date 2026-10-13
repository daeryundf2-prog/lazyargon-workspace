#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
exif_audit.py — 이미지 EXIF/메타데이터 포렌식 감사

사진 증거의 EXIF를 읽어 촬영일시·기기·GPS·편집 흔적을 표면 조사한다.
Pillow가 없으면 exit 3(fail-closed). 메타데이터 부재 자체가
신호(소셜앱 경유·재저장 가능성)가 될 수 있으므로 결측도 기록한다.

사용:
    python scripts/exif_audit.py photo.jpg
    python scripts/exif_audit.py media/ --json
    python scripts/exif_audit.py media/ -o exif_report.json

보고 항목:
    - DateTimeOriginal / Make / Model / Software(편집기 흔적)
    - GPS 여부 / EXIF 완전 부재 여부

알려진 한계:
- EXIF는 자유롭게 편집 가능하다. '기록된 값'이 아니라 '파일에 적힌
  값'으로만 보고할 것. 촬영 시점 확정 수단이 아니다.
- EXIF가 지워진 파일이 '조작됐다'는 뜻이 아니다 — 대부분의 메신저
  경유 이미지는 EXIF가 없다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

IMG_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".webp", ".heic", ".bmp"}

# Pillow tag id → 이름 (주요 항목만)
TAG_NAMES = {
    0x010F: "Make", 0x0110: "Model", 0x0131: "Software",
    0x0132: "DateTime", 0x9003: "DateTimeOriginal", 0x9004: "DateTimeDigitized",
    0x8825: "GPSInfo", 0x829A: "ExposureTime", 0x829D: "FNumber",
    0x8827: "ISO", 0xA434: "LensModel",
}


def _require_pillow():
    try:
        from PIL import Image  # type: ignore
        return Image
    except ImportError:
        print("Pillow가 없습니다: pip install 'pillow>=10.0,<12'", file=sys.stderr)
        return None


def audit_image(path: Path, Image) -> dict:
    rec: dict = {"file": str(path)}
    try:
        with Image.open(path) as img:
            rec["format"] = img.format
            rec["size"] = f"{img.width}x{img.height}"
            exif = img.getexif()
            if not exif:
                rec["exif_present"] = False
                rec["note"] = "EXIF 없음 — 메신저 경유·재저장 가능성"
                return rec
            rec["exif_present"] = True
            tags = {}
            for tag_id, value in exif.items():
                name = TAG_NAMES.get(tag_id)
                if name:
                    tags[name] = str(value)[:100]
            # IFD 안의 DateTimeOriginal 등은 get_ifd로
            try:
                ifd = exif.get_ifd(0x8769)  # ExifIFD
                for tag_id, value in ifd.items():
                    name = TAG_NAMES.get(tag_id)
                    if name:
                        tags[name] = str(value)[:100]
            except Exception:  # noqa: BLE001
                pass
            rec["tags"] = tags
            rec["has_gps"] = "GPSInfo" in tags or 0x8825 in exif
            rec["has_software"] = "Software" in tags
            if rec["has_software"]:
                rec["note"] = "편집 소프트웨어 흔적 있음 — 원본성 검토 필요"
    except Exception as e:  # noqa: BLE001 — 손상 파일은 실패로 기록
        rec["error"] = str(e)[:200]
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="이미지 EXIF/메타데이터 포렌식 감사")
    ap.add_argument("input", help="이미지 파일 또는 디렉터리")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("-o", "--output", default=None, help="JSON 리포트 출력 경로")
    args = ap.parse_args(argv)

    Image = _require_pillow()
    if Image is None:
        return 3

    target = Path(args.input)
    if target.is_dir():
        files = sorted(p for p in target.rglob("*") if p.suffix.lower() in IMG_EXTS)
    elif target.is_file():
        files = [target]
    else:
        print(f"대상을 찾을 수 없습니다: {target}", file=sys.stderr)
        return 2
    if not files:
        print(f"이미지 파일이 없습니다: {target}", file=sys.stderr)
        return 2

    records = [audit_image(f, Image) for f in files]
    summary = {
        "total": len(records),
        "exif_present": sum(1 for r in records if r.get("exif_present")),
        "exif_absent": sum(1 for r in records if r.get("exif_present") is False),
        "with_gps": sum(1 for r in records if r.get("has_gps")),
        "with_software": sum(1 for r in records if r.get("has_software")),
        "errors": sum(1 for r in records if "error" in r),
        "records": records,
    }

    if args.output:
        Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        print(f"→ {args.output}")
    elif args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"{summary['total']}개 이미지: EXIF 있음 {summary['exif_present']}, "
              f"없음 {summary['exif_absent']}, GPS {summary['with_gps']}, "
              f"편집흔적 {summary['with_software']}")
        for r in records:
            if r.get("error"):
                print(f"  [ERR] {r['file']}: {r['error']}")
            elif r.get("exif_present"):
                t = r["tags"]
                print(f"  {r['file']}: {t.get('Make','?')} {t.get('Model','?')} "
                      f"촬영 {t.get('DateTimeOriginal','기록없음')}"
                      + (" [GPS]" if r["has_gps"] else "")
                      + (f" [SW:{t.get('Software')}]" if r.get("has_software") else ""))
            else:
                print(f"  {r['file']}: EXIF 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
