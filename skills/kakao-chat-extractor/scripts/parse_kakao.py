#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_kakao.py
Parse KakaoTalk text exports (mobile + PC "대화내용 저장").

Supported inputs (text exports only):
- Mobile: "--- YYYY년 M월 D일 요일 ---" 헤더 + "[닉네임] [오전/오후 h:mm] 메시지"
- PC: "=== YYYY년 M월 D일 요일 ===" 헤더 + "[오전/오후 h:mm(:ss)] 닉네임 : 메시지"
- Legacy synthetic PC line "[YYYY-MM-DD HH:MM:SS] 닉네임: 메시지" (이전 버전 호환)

Does not read Kakao SQLite, chat_logs, Android/iOS backups, or encrypted
chat databases. Mobile exports have no seconds; those timestamps end with :00.

Fail-closed 규약:
- 발신/수신과 무관한 '사진'/'동영상' 단어 언급은 첨부로 판정하지 않는다.
  첨부는 내보내기 포맷이 사용하는 확정 표기(사진 / 파일: ... 등)만 인정한다.
- '...님이 나갔습니다.' 같은 시스템 이벤트와 인식 불가 행은 메시지에 병합하지
  않고 type 필드로 별도 레코드로 내보낸다 (증거 텍스트를 조용히 버리지 않는다).
"""

import argparse
import json
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DATE_HEADER_REGEX = re.compile(r"^[-=]{2,}\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일.*[-=]{2,}$")
MOBILE_MSG_REGEX = re.compile(r"^\[(.+?)\]\s*\[(오전|오후)\s*(\d{1,2}):(\d{2})\]\s*(.*)$")
PC_MSG_REGEX = re.compile(
    r"^\[(오전|오후)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*(.+?)\s*:\s+(.*)$"
)  # 실제 PC 내보내기: [오후 2:15] 닉네임 : 메시지 (초 있음/없음 모두)
LEGACY_PC_MSG_REGEX = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\]\s*(.+?)\s*:\s+(.*)$"
)  # 이전 버전이 문서화했던 합성 포맷 (하위 호환)
SYSTEM_EVENT_REGEX = re.compile(
    r"^.+?님이\s+(?:.+을\s+)?(?:들어왔습니다|나갔습니다|초대했습니다|퇴장했습니다)\.$"
)
SYSTEM_TIME_PREFIX_RE = re.compile(
    r"^\[(오전|오후)\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\]\s*"
)  # PC 내보내기의 시스템 이벤트는 [시각] 접두어가 붙기도 한다

# 내보내기에서 첨부가 확정 표기로 나타나는 형태만 인정한다.
ATTACHMENT_PLACEHOLDER_RE = re.compile(
    r"^(?:사진|동영상|동영상 파일|음성메모|음성메모 파일|음성 메모|멀티프로필 사진|프로필 사진|파일 전송)"
    r"(?:\s+\d+\s*(?:장|개))?$"
)
ATTACHMENT_FILE_PREFIX_RE = re.compile(r"^(?:파일|File|file)\s*:")


def detect_attachment(content):
    c = content.strip()
    return bool(ATTACHMENT_PLACEHOLDER_RE.match(c) or ATTACHMENT_FILE_PREFIX_RE.match(c))


def read_kakao_text(filepath):
    """BOM → UTF-8 → CP949(한국어 Windows 레거시) → UTF-16 순으로 시도한다.

    구버전은 CP949 내보내기에서 UnicodeDecodeError 로 미처리 크래시하거나
    mojibake 로 조용히 잘못 읽었다.
    """
    with open(filepath, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    attempted = []
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError as exc:
            attempted.append(f"{enc}: {exc}")
    if len(raw) % 2 == 0:
        try:
            return raw.decode("utf-16")
        except UnicodeDecodeError as exc:
            attempted.append(f"utf-16: {exc}")
    raise ValueError(
        "입력 파일 인코딩을 판별할 수 없습니다 (시도: " + "; ".join(attempted) + ")"
    )


def _base_record(record_type, current_date):
    return {
        "type": record_type,
        "timestamp": None,
        "timestamp_unknown": current_date is None,
        "sender": None,
        "message": "",
        "has_attachment": False,
    }


def parse_kakao_text(text):
    records = []
    current_date = None

    for line in text.splitlines():
        line_str = line.rstrip()
        stripped = line_str.strip()
        if not stripped:
            continue

        date_match = DATE_HEADER_REGEX.match(stripped)
        if date_match:
            y, m, d = date_match.groups()
            current_date = f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
            continue

        mob_match = MOBILE_MSG_REGEX.match(stripped)
        if mob_match:
            user, ampm, hour, minute, content = mob_match.groups()
            h = int(hour)
            if ampm == "오후" and h != 12:
                h += 12
            elif ampm == "오전" and h == 12:
                h = 0
            ts = (
                f"{current_date} {h:02d}:{int(minute):02d}:00"
                if current_date is not None
                else None
            )
            records.append({
                "type": "message",
                "timestamp": ts,
                "timestamp_unknown": current_date is None,
                "sender": user,
                "message": content,
                "has_attachment": detect_attachment(content),
                "second_precision": "export-has-no-seconds",
            })
            continue

        pc_match = PC_MSG_REGEX.match(stripped)
        if pc_match:
            ampm, hour, minute, seconds, user, content = pc_match.groups()
            h = int(hour)
            if ampm == "오후" and h != 12:
                h += 12
            elif ampm == "오전" and h == 12:
                h = 0
            ts = (
                f"{current_date} {h:02d}:{int(minute):02d}"
                + (f":{seconds}" if seconds else ":00")
                if current_date is not None
                else None
            )
            records.append({
                "type": "message",
                "timestamp": ts,
                "timestamp_unknown": current_date is None,
                "sender": user,
                "message": content,
                "has_attachment": detect_attachment(content),
                "second_precision": "as-exported" if seconds else "export-has-no-seconds",
            })
            continue

        legacy_pc_match = LEGACY_PC_MSG_REGEX.match(stripped)
        if legacy_pc_match:
            ts, user, content = legacy_pc_match.groups()
            records.append({
                "type": "message",
                "timestamp": ts,
                "timestamp_unknown": False,
                "sender": user,
                "message": content,
                "has_attachment": detect_attachment(content),
                "second_precision": "as-exported",
            })
            continue

        # 시스템 이벤트: '[시각] ...님이 나갔습니다.' / '...님이 나갔습니다.' 모두 지원
        event_body = stripped
        event_time = None
        sys_time_match = SYSTEM_TIME_PREFIX_RE.match(event_body)
        if sys_time_match:
            ampm, hour, minute, seconds = sys_time_match.groups()
            event_body = event_body[sys_time_match.end():]
            h = int(hour)
            if ampm == "오후" and h != 12:
                h += 12
            elif ampm == "오전" and h == 12:
                h = 0
            event_time = (
                f"{h:02d}:{int(minute):02d}" + (f":{seconds}" if seconds else ":00")
            )
        if SYSTEM_EVENT_REGEX.match(event_body):
            record = _base_record("system", current_date)
            record["message"] = event_body
            if current_date is not None and event_time is not None:
                record["timestamp"] = f"{current_date} {event_time}"
                record["timestamp_unknown"] = False
            records.append(record)
            continue

        # 나머지 줄: 직전이 'message' 면 다 줄 본문(개행 보존), 아니면 unparsed 레코드.
        # (구버전은 직전 레코드 종류와 무관하게 병합해 나감/초대 이벤트를 메시지에
        #  섞었고, 선행 메시지가 없는 헤더 노이즈는 조용히 버렸다)
        if records and records[-1]["type"] == "message":
            records[-1]["message"] += "\n" + line_str
        else:
            record = _base_record("unparsed", current_date)
            record["message"] = stripped
            records.append(record)

    return records


def parse_kakao_file(filepath):
    return parse_kakao_text(read_kakao_text(filepath))


def records_to_events(records):
    """forensic-timeline 의 events.json 호환 형식으로 변환.

    시각이 확정된 message/system 레코드만 옮긴다 — unparsed 와 시각 미상 레코드는
    '근거 없는 시각'이므로 타임라인에 넣지 않는다 (fail-closed).
    """
    events = []
    for r in records:
        if r.get("type") not in ("message", "system"):
            continue
        ts = r.get("timestamp")
        if not ts:
            continue
        sender = r.get("sender")
        prefix = f"[{sender}] " if sender else "[시스템] "
        events.append({
            "timestamp": ts,
            "description": (prefix + (r.get("message") or "")).strip(),
            "category": "system" if r["type"] == "system" else "chat",
        })
    return events


def main(argv=None):
    parser = argparse.ArgumentParser(description="KakaoTalk text-export parser")
    parser.add_argument("input", help="KakaoTalk text export file")
    parser.add_argument("--output", help="Output JSON file path (records)")
    parser.add_argument("--events-out", dest="events_out",
                        help="forensic-timeline 호환 events.json 출력 경로 "
                             "(시각이 확정된 message/system 레코드만 포함)")
    parser.add_argument("--keyword", help="Filter messages containing keyword")
    args = parser.parse_args(argv)

    try:
        records = parse_kakao_file(args.input)
    except OSError as exc:
        print(f"[-] Failed to read input: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"[-] {exc}", file=sys.stderr)
        return 2

    total = len(records)
    messages = [r for r in records if r["type"] == "message"]
    if args.keyword:
        kw = args.keyword.lower()
        records = [
            r for r in records
            if kw in (r.get("message") or "").lower() or kw in (r.get("sender") or "").lower()
        ]

    print(f"[+] Total parsed records: {total} (messages: {len(messages)})")
    if args.keyword:
        print(f"[+] Keyword filter: {len(records)} records match")
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        print(f"[+] Saved to: {args.output}")
    if args.events_out:
        events = records_to_events(records)
        with open(args.events_out, "w", encoding="utf-8") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
        print(f"[+] Timeline events: {len(events)} -> {args.events_out}")
        if not events:
            print("[!] 시각이 확정된 레코드가 없어 타임라인 이벤트가 0건이다 — "
                  "내보내기 파일에 날짜 헤더가 있는지 확인할 것.", file=sys.stderr)
    if not args.output and not args.events_out:
        for r in records[:10]:
            ts = r.get("timestamp") or "시각미상"
            preview = (r.get("message") or "")[:60].replace("\n", " ")
            sender = r.get("sender") or r["type"]
            print(f"[{ts}] {sender}: {preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
