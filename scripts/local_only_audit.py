#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
local_only_audit.py — 외부 반출 가능 코드 경로 정적 감사

'의뢰인 데이터를 외부로 보내지 않는다'는 계약을 글이 아니라 실행으로 확인한다.
플러그인 스크립트/스킬을 정적으로 훑어 네트워크 송신 가능 지점(egress)을
목록화하고, 각 지점이 명시적 승인 플래그(--upload-audio, allow_upload 등)
뒤에 있는지 분류한다.

사용:
    python scripts/local_only_audit.py                    # 플러그인 전체 감사
    python scripts/local_only_audit.py --json
    python scripts/local_only_audit.py --env              # API 키 환경변수 점검

판정:
    - egress + 승인 플래그 존재 = GATED (의도된 경로)
    - egress + 승인 플래그 없음 = UNGATED (검토 필요)
    - UNGATED + allowlist 등재 = REVIEWED (사람이 검토 완료한 경로)

allowlist: `<root>/.local_only_allowlist` — 한 줄에 `relpath kind`
(예: `scripts/download_dfir_binaries.ps1 http_call`). `#`은 주석.
파일+종류 단위로 등재되므로 같은 파일의 다른 종류의 새 송신 경로는
여전히 UNGATED로 잡힌다.

알려진 한계:
- 정적 패턴 검사다. subprocess로 다른 바이너리를 호출해 그쪽에서 나가는
  트래픽은 감지하지 못한다. 실제 반출 차단은 방화벽/네임스페이스 격리가 맡는다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ["scripts", "skills"]
CODE_EXTS = {".py", ".mjs", ".js", ".sh", ".ps1"}

EGRESS_PATTERNS = [
    (re.compile(r"urllib\.request|urlopen|requests\.|http\.client|\bfetch\(|axios|curl |Invoke-WebRequest|wget "), "http_call"),
    (re.compile(r"api\.openai|groq\.com|api\.anthropic|generativelanguage|open\.law\.go\.kr"), "known_api_endpoint"),
    (re.compile(r"socket\.|smtplib|ftplib"), "socket_or_mail"),
]

GATE_HINTS = re.compile(
    r"allow_upload|upload_audio|--upload|GROQ_API_KEY|OPENAI_API_KEY|LAW_OC|API_KEY|approve|consent|동의"
)

# 승인 힌트는 각 송신 지점 ±N 줄 안에 있어야 GATED로 인정한다 — 파일 어딘가에
# "동의 필요"가 적혀 있기만 해도 모든 egress가 통과하는 허점을 막기 위함.
GATE_PROXIMITY_LINES = 5

ENV_KEYS = ["GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LAW_OC"]


def load_allowlist(root: Path, explicit: str | None) -> set[tuple[str, str]]:
    """`relpath kind` 쌍의 집합을 읽는다. 파일이 없으면 빈 집합."""
    path = Path(explicit) if explicit else root / ".local_only_allowlist"
    entries: set[tuple[str, str]] = set()
    if not path.is_file():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            entries.add((Path(parts[0]).as_posix(), parts[1]))
    return entries


def scan_file(path: Path, base: Path, allowlist: set[tuple[str, str]]) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    findings = []
    gate_lines = [i for i, line in enumerate(lines, 1) if GATE_HINTS.search(line)]
    rel = Path(path.relative_to(base)).as_posix()
    for i, line in enumerate(lines, 1):
        for pattern, kind in EGRESS_PATTERNS:
            if pattern.search(line):
                # per-egress 근접 검사: 근처 힌트가 없으면 UNGATED로 남겨
                # 사람 검토를 요구한다 (모호하면 경고 쪽으로 — fail-closed).
                gated = any(abs(i - g) <= GATE_PROXIMITY_LINES for g in gate_lines)
                if gated:
                    status = "GATED"
                elif (rel, kind) in allowlist:
                    status = "REVIEWED"
                else:
                    status = "UNGATED"
                findings.append({
                    "file": rel,
                    "line": i,
                    "kind": kind,
                    "code": line.strip()[:120],
                    "status": status,
                })
                break
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="외부 반출 가능 경로 정적 감사")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    ap.add_argument("--env", action="store_true", help="API 키 환경변수 존재 여부도 점검")
    ap.add_argument("--root", default=None, help="감사 루트 (기본: 플러그인 루트)")
    ap.add_argument("--allowlist", default=None,
                    help="검토 완료 목록 파일 (기본: <root>/.local_only_allowlist)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else PLUGIN_ROOT
    allowlist = load_allowlist(root, args.allowlist)
    all_findings: list[dict] = []
    scanned = 0
    for sub in SCAN_DIRS:
        base = root / sub
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if (f.suffix.lower() in CODE_EXTS and "__pycache__" not in f.parts
                    and f.name != "local_only_audit.py"):
                scanned += 1
                all_findings.extend(scan_file(f, root, allowlist))

    ungated = [f for f in all_findings if f["status"] == "UNGATED"]
    gated = [f for f in all_findings if f["status"] == "GATED"]
    reviewed = [f for f in all_findings if f["status"] == "REVIEWED"]

    result = {
        "root": str(root),
        "files_scanned": scanned,
        "egress_points": len(all_findings),
        "gated": len(gated),
        "reviewed": len(reviewed),
        "ungated": len(ungated),
        "findings": all_findings,
    }

    if args.env:
        result["env_keys_present"] = {k: bool(os.getenv(k)) for k in ENV_KEYS}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"스캔 파일 {scanned}개, 외부 송신 가능 지점 {len(all_findings)}곳 "
              f"(GATED {len(gated)} / REVIEWED {len(reviewed)} / UNGATED {len(ungated)})")
        for f in all_findings:
            mark = {"GATED": "GATED  ", "REVIEWED": "REVIEW ", "UNGATED": "UNGATED"}[f["status"]]
            print(f"  [{mark}] {f['file']}:{f['line']}  {f['kind']}  {f['code'][:80]}")
        if ungated:
            print("\nUNGATED 지점은 검토가 필요합니다 — 의도된 경로면 승인 플래그를 명시하거나,\n"
                  "검토 완료 후 .local_only_allowlist에 `파일 종류`로 등재하세요.")
        if args.env:
            print("\n환경변수:", {k: v for k, v in result["env_keys_present"].items()})

    return 1 if ungated else 0


if __name__ == "__main__":
    sys.exit(main())
