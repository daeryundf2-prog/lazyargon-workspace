#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_timeline.py — 다중 소스 시각을 단일 events.json으로 병합

forensic-timeline(--input events.json)에 넣을 정규화 이벤트 목록을 만든다.
지원 소스:

  --manifest m.json     evidence_manifest.py 출력 → 파일 수정시각(mtime)
  --kakao k.json        parse_kakao.py 출력 → 메시지 수발신 시각
  --exif e.json         exif_audit.py --json 출력 → DateTimeOriginal
  --stt t.json          local_stt.py 전사 JSON → 발화 구간
  --plaso p.{jsonl,csv} log2timeline 슈퍼 타임라인 출력 → 통합 이벤트

STT 구간의 시각은 '녹음 파일 내 상대 초'다. 벽시계로 올리려면
기준 시각을 명시해야 한다:

  --stt call.wav.transcript.json --anchor call.wav="2026-09-11T14:03:00+09:00"

--anchor 없이 들어온 STT는 events에 넣지 않고 'unanchored' 목록으로
분리해 보고한다 — 상대 초를 벽시계로 지어내지 않는다.

사용:
    python scripts/merge_timeline.py --manifest m.json --kakao k.json -o events.json
    python scripts/merge_timeline.py ... -o events.json && \\
      python skills/forensic-timeline/scripts/generate_timeline.py \\
        --input events.json --output timeline.html

알려진 한계:
- mtime·EXIF·카톡 시각은 '기록된 값'이지 진실이 아니다 — 타임스탬프
  위조 가능성은 별도 검증 대상.
- 카톡보내기 초 단위 없는 포맷은 초가 00으로 표기된다(파서 한계).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))


def _load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _norm_iso(raw: str) -> str | None:
    """'YYYY-MM-DD HH:MM:SS' 또는 ISO → ISO(+09:00). 실패 시 None."""
    s = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.isoformat()
    except ValueError:
        pass
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$", s)
    if m:
        y, mo, d, h, mi, sec = m.groups()
        return datetime(int(y), int(mo), int(d), int(h), int(mi),
                        int(sec or 0), tzinfo=KST).isoformat()
    return None


def _norm_exif_dt(raw: str) -> str | None:
    """EXIF 'YYYY:MM:DD HH:MM:SS' → ISO(+09:00)."""
    m = re.match(r"^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})", raw.strip())
    if not m:
        return None
    return datetime(*[int(g) for g in m.groups()], tzinfo=KST).isoformat()


def events_from_manifest(path: str) -> list[dict]:
    data = _load_json(path)
    files = data.get("files", [])
    out = []
    for f in files:
        ts = _norm_iso(f.get("mtime", ""))
        out.append({"timestamp": ts or f.get("mtime", ""), "source": "파일시스템",
                    "description": f"파일 수정(기록값): {f['path']}",
                    "file": f["path"], "sha256": f.get("sha256", "")[:16]})
    return out


def events_from_kakao(path: str) -> list[dict]:
    data = _load_json(path)
    records = data.get("records", data) if isinstance(data, dict) else data
    out = []
    for r in records:
        if r.get("type") != "message":
            continue
        ts = _norm_iso(r.get("timestamp") or "")
        if ts is None:
            continue  # 시각 불명 메시지는 타임라인에 올리지 않는다
        out.append({"timestamp": ts, "source": "카카오톡",
                    "description": f"{r.get('sender', '?')}: "
                                   f"{str(r.get('message', ''))[:80]}",
                    "file": path})
    return out


def events_from_exif(path: str) -> list[dict]:
    data = _load_json(path)
    records = data.get("records", []) if isinstance(data, dict) else data
    out = []
    for r in records:
        dto = (r.get("tags") or {}).get("DateTimeOriginal")
        if not dto:
            continue
        ts = _norm_exif_dt(dto)
        if ts is None:
            continue
        out.append({"timestamp": ts, "source": "EXIF",
                    "description": f"촬영(기록값): {Path(r['file']).name}",
                    "file": r["file"]})
    return out


def events_from_stt(path: str, anchors: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """(anchored 이벤트, unanchored 기록)를 반환한다."""
    data = _load_json(path)
    segs = data.get("segments", [])
    # 전사 파일명에서 원본 오디오명 추정: x.wav.transcript.json → x.wav
    stem = Path(path).name
    audio_name = stem[:-len(".transcript.json")] if stem.endswith(".transcript.json") else stem
    anchor_iso = anchors.get(audio_name) or anchors.get(stem)
    anchored, unanchored = [], []
    for s in segs:
        if s.get("start") is None:
            unanchored.append({"file": audio_name, "text": s.get("text", "")[:80],
                               "reason": "엔진이 타임스탬프 미제공"})
            continue
        if anchor_iso is None:
            unanchored.append({"file": audio_name,
                               "offset_sec": s["start"],
                               "text": s.get("text", "")[:80],
                               "reason": "녹음 기준시각 미지정"})
            continue
        base = datetime.fromisoformat(anchor_iso)
        ts = base + timedelta(seconds=float(s["start"]))
        anchored.append({"timestamp": ts.isoformat(), "source": "STT(앵커 추정)",
                         "description": f"발화: {s.get('text', '')[:80]}",
                         "file": audio_name,
                         "note": f"기준 {anchor_iso} + {s['start']}s"})
    return anchored, unanchored


def _plaso_record_event(rec: dict, path: str) -> dict | None:
    """Plaso(json_line/CSV) 레코드 한 건을 통합 이벤트로 변환. 시각 없으면 None."""
    ts = None
    # plaso json_line: timestamp는 epoch microseconds, datetime은 ISO 문자열
    raw_ts = rec.get("timestamp")
    if raw_ts is not None:
        try:
            ts = datetime.fromtimestamp(int(raw_ts) / 1_000_000, tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            ts = None
    if ts is None:
        for key in ("datetime", "date_time"):
            if rec.get(key):
                ts = _norm_iso(str(rec[key]))
                if ts:
                    break
    if ts is None:
        return None
    desc = rec.get("message") or rec.get("display_name") or rec.get("filename") or "(항목)"
    return {
        "timestamp": ts,
        "source": f"plaso:{rec.get('parser') or rec.get('source') or 'unknown'}",
        "description": f"[{rec.get('timestamp_desc', 'event')}] {str(desc)[:80]}",
        "file": path,
    }


def events_from_plaso(path: str) -> list[dict]:
    """log2timeline 출력(JSONL 또는 CSV) → 통합 이벤트 목록."""
    import csv
    import io

    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    records: list[dict] = []
    if raw.lstrip().startswith("{"):
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    else:
        records = list(csv.DictReader(io.StringIO(raw)))
    out = []
    for r in records:
        ev = _plaso_record_event(r, path)
        if ev:
            out.append(ev)
    return out


def merge(manifests, kakaos, exifs, stts, anchors, plasos=None) -> dict:
    events, unanchored = [], []
    for p in manifests:
        events += events_from_manifest(p)
    for p in kakaos:
        events += events_from_kakao(p)
    for p in exifs:
        events += events_from_exif(p)
    for p in plasos or []:
        events += events_from_plaso(p)
    for p in stts:
        a, u = events_from_stt(p, anchors)
        events += a
        unanchored += u
    def sort_key(event):
        try:
            ts = datetime.fromisoformat(str(event.get("timestamp", "")).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                return (1, datetime.min.replace(tzinfo=timezone.utc))
            return (0, ts.astimezone(timezone.utc))
        except (ValueError, TypeError):
            return (1, datetime.min.replace(tzinfo=timezone.utc))

    events.sort(key=sort_key)
    return {"events": events, "unanchored_stt": unanchored}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="다중 소스 시각 → events.json 병합")
    ap.add_argument("--manifest", action="append", default=[])
    ap.add_argument("--kakao", action="append", default=[])
    ap.add_argument("--exif", action="append", default=[])
    ap.add_argument("--stt", action="append", default=[])
    ap.add_argument("--plaso", action="append", default=[],
                    help="log2timeline 출력(JSONL/CSV) — 슈퍼 타임라인 병합")
    ap.add_argument("--anchor", action="append", default=[],
                    help='오디오파일명="ISO시각" — STT 상대시각의 벽시계 기준')
    ap.add_argument("-o", "--output", default=None, help="events.json 경로")
    ap.add_argument("--report", default=None, help="병합 요약 JSON 경로")
    args = ap.parse_args(argv)

    if not (args.manifest or args.kakao or args.exif or args.stt or args.plaso):
        print("입력 소스가 없습니다. --manifest/--kakao/--exif/--stt/--plaso 중 하나 이상 지정.",
              file=sys.stderr)
        return 2

    anchors = {}
    for a in args.anchor:
        if "=" not in a:
            print(f"--anchor 형식 오류(파일=시각 필요): {a}", file=sys.stderr)
            return 2
        k, v = a.split("=", 1)
        anchors[k.strip()] = v.strip().strip('"')

    merged = merge(args.manifest, args.kakao, args.exif, args.stt, anchors, plasos=args.plaso)

    out = json.dumps(merged["events"], ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    else:
        print(out)
    if args.report:
        Path(args.report).write_text(json.dumps({
            "event_count": len(merged["events"]),
            "unanchored_stt": merged["unanchored_stt"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    n_un = len(merged["unanchored_stt"])
    print(f"이벤트 {len(merged['events'])}건 병합"
          + (f", STT 상대시각 {n_un}건은 미배치(--anchor 필요)" if n_un else ""),
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
