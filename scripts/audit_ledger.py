#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audit_ledger.py — 에이전트/분석관 작업의 append-only 감사 원장 (tamper-evident)

maka(apache/maka)의 Runtime Event Log 패턴을 경량 차용한 로컬 원장이다.
도구 호출·파일 수정·보고서 생성 같은 작업 이벤트를 JSONL로 순서대로 기록하고,
각 항목이 이전 항목의 해시를 포함하는 SHA-256 체인으로 연결된다.

⚠️ 한계 (사실성 필수):
  이 체인은 *tamper-evident*(변조 탐지 가능)이지 tamper-proof(변조 불가능)가
  아니다. 원장 파일 전체를 처음부터 재계산하면 로컬만으로는 탐지할 수 없다.
  사법 소명력을 가지려면 외부 앵커가 필요하다:

    - `anchor` 서브커맨드는 헤드 해시의 RFC 3161 타임스탬프 요청(.tsq)을
      생성한다(openssl 필요, BYOB). TSA 응답(.tsr)을 받으면
      `anchor-check`로 검증한다.
    - 또는 헤드 해시를 외부 매체(이메일 발송, 공증, 별도 저장소)에 고정한다.

사용:
    python scripts/audit_ledger.py record ledger.jsonl --kind tool_call \
        --actor local_stt.py --detail "call.wav 전사" --payload-file out.json
    python scripts/audit_ledger.py verify ledger.jsonl
    python scripts/audit_ledger.py head ledger.jsonl
    python scripts/audit_ledger.py anchor ledger.jsonl            # .tsq 생성
    python scripts/audit_ledger.py anchor-check ledger.jsonl resp.tsr \
        --ca cert.pem --untrusted chain.pem
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(obj: dict) -> bytes:
    """결정적 직렬화 — 해시 입력의 재현성을 보장한다."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def entry_hash(entry: dict) -> str:
    """entry_hash 필드 자신을 제외한 항목의 SHA-256."""
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return hashlib.sha256(_canonical(body)).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> list[dict]:
    entries = []
    if not path.exists():
        return entries
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise SystemExit(f"원장 파싱 실패 line {i + 1}: {e}")
    return entries


def verify(path: Path) -> tuple[bool, int | None, str]:
    """체인 검증. (ok, 첫 파손 index 또는 None, 메시지)를 반환한다."""
    entries = load(path)
    prev = GENESIS
    for i, e in enumerate(entries):
        if e.get("prev_hash") != prev:
            return False, i, f"prev_hash 불일치 (기대 {prev[:12]}…, 기록 {str(e.get('prev_hash'))[:12]}…)"
        if e.get("entry_hash") != entry_hash(e):
            return False, i, "entry_hash 재계산 불일치 — 항목 내용 변조"
        prev = e["entry_hash"]
    return True, None, f"{len(entries)}개 항목 체인 무결"


def record(path: Path, kind: str, actor: str, detail: str,
           payload_file: Path | None) -> dict:
    entries = load(path)
    if entries:
        prev = entries[-1].get("entry_hash")
        if not isinstance(prev, str) or not prev:
            # 손상/변조된 원장 위에 새 항목을 얹으면 체인 전체가 무의미해진다 —
            # 날것의 KeyError 대신 무엇이 깨졌는지 알린다 (fail-closed).
            raise SystemExit(
                f"원장 마지막 항목(seq {len(entries) - 1})에 entry_hash가 없습니다 — "
                f"원장이 손상되었거나 변조되었을 수 있습니다. "
                f"`verify {path}`로 체인을 확인하고 신뢰 가능한 사본에서 복구하세요")
    else:
        prev = GENESIS
    entry = {
        "seq": len(entries),
        "ts_utc": _utcnow(),
        "kind": kind,
        "actor": actor,
        "detail": detail,
        "prev_hash": prev,
    }
    if payload_file is not None:
        entry["payload_sha256"] = file_sha256(payload_file)
    entry["entry_hash"] = entry_hash(entry)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def head(path: Path) -> str | None:
    entries = load(path)
    if not entries:
        return None
    h = entries[-1].get("entry_hash")
    if not isinstance(h, str) or not h:
        raise SystemExit(
            f"원장 마지막 항목(seq {len(entries) - 1})에 entry_hash가 없습니다 — "
            f"원장이 손상되었거나 변조되었을 수 있습니다. `verify {path}`로 확인하세요")
    return h


def make_tsa_request(path: Path) -> Path:
    """헤드 해시로 RFC 3161 타임스탬프 요청(.tsq)을 생성한다. openssl 필요."""
    h = head(path)
    if h is None:
        raise SystemExit("원장이 비어 있어 앵커링할 헤드 해시가 없습니다")
    openssl = shutil.which("openssl")
    if openssl is None:
        raise SystemExit("openssl이 없습니다. TSA 요청 생성 불가(BYOB)")
    digest_file = path.with_suffix(".head.sha256")
    digest_file.write_text(h + "\n", encoding="utf-8")
    tsq = path.with_suffix(".tsq")
    proc = subprocess.run(
        [openssl, "ts", "-query", "-digest", h, "-sha256", "-cert", "-out", str(tsq)],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise SystemExit(f"openssl ts -query 실패: {proc.stderr.strip()[:300]}")
    return tsq


def check_tsa_reply(path: Path, tsr: Path, ca: Path | None, untrusted: Path | None) -> bool:
    """TSA 응답(.tsr)이 현재 헤드 해시의 것인지 openssl로 검증한다."""
    openssl = shutil.which("openssl")
    if openssl is None:
        raise SystemExit("openssl이 없습니다. 검증 불가(BYOB)")
    h = head(path)
    if h is None:
        raise SystemExit("원장이 비어 있습니다")
    digest_file = path.with_suffix(".head.sha256")
    digest_file.write_text(h + "\n", encoding="utf-8")
    cmd = [openssl, "ts", "-verify", "-digest", h, "-in", str(tsr)]
    if ca:
        cmd += ["-CAfile", str(ca)]
    if untrusted:
        cmd += ["-untrusted", str(untrusted)]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok = proc.returncode == 0
    print(proc.stdout.strip() or proc.stderr.strip())
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="append-only 감사 원장 (tamper-evident, 외부 앵커 슬롯)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="이벤트 추가")
    p_rec.add_argument("ledger", type=Path)
    p_rec.add_argument("--kind", required=True, help="이벤트 종류 (tool_call, file_write, report …)")
    p_rec.add_argument("--actor", required=True, help="수행 주체 (스크립트/분석관 식별자)")
    p_rec.add_argument("--detail", default="", help="이벤트 설명")
    p_rec.add_argument("--payload-file", type=Path, default=None,
                       help="산출물 파일 — SHA-256이 항목에 기록된다")

    p_ver = sub.add_parser("verify", help="체인 검증")
    p_ver.add_argument("ledger", type=Path)

    p_head = sub.add_parser("head", help="헤드 해시 출력")
    p_head.add_argument("ledger", type=Path)

    p_anc = sub.add_parser("anchor", help="헤드 해시의 RFC 3161 .tsq 생성 (openssl 필요)")
    p_anc.add_argument("ledger", type=Path)

    p_chk = sub.add_parser("anchor-check", help="TSA 응답(.tsr) 검증")
    p_chk.add_argument("ledger", type=Path)
    p_chk.add_argument("tsr", type=Path)
    p_chk.add_argument("--ca", type=Path, default=None)
    p_chk.add_argument("--untrusted", type=Path, default=None)

    args = ap.parse_args(argv)

    if args.cmd == "record":
        if args.payload_file is not None and not args.payload_file.exists():
            print(f"payload 파일이 없습니다: {args.payload_file}", file=sys.stderr)
            return 2
        e = record(args.ledger, args.kind, args.actor, args.detail, args.payload_file)
        print(f"[{e['seq']}] {e['entry_hash'][:16]}…  {e['kind']} by {e['actor']}")
        return 0
    if args.cmd == "verify":
        ok, idx, msg = verify(args.ledger)
        print(("OK — " if ok else f"BROKEN @ seq {idx} — ") + msg)
        return 0 if ok else 1
    if args.cmd == "head":
        h = head(args.ledger)
        print(h if h else "(empty)")
        return 0 if h else 1
    if args.cmd == "anchor":
        tsq = make_tsa_request(args.ledger)
        print(f"TSA 요청 생성 → {tsq}  (TSA에 제출해 .tsr을 받은 뒤 anchor-check로 검증)")
        return 0
    if args.cmd == "anchor-check":
        return 0 if check_tsa_reply(args.ledger, args.tsr, args.ca, args.untrusted) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
