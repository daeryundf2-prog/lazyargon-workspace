#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
case_envelope.py — 레포 간 산출물을 lazy-evidence-case-v1 봉투로 변환.

레포를 합치지 않고 파일로 통신한다 (contract federation). 각 생산 레포의
기존 산출물을 읽어 공통 스키마 문서로 감싼다:

    frametrace   package-manifest.json  → file items (trust=observed)
    rapid        results JSON           → file items (trust=observed)
    deepfake     scan JSON              → screening_result (model-assisted)
    ledger       audit_ledger JSONL     → audit_event (observed, ledger_ref)

사용:
    python scripts/case_envelope.py build --case-id CASE-001 \
        --producer-repo lazyforensic --producer-tool scripts/case_envelope.py \
        --input frametrace:pkg/package-manifest.json \
        --input deepfake:scan.json --out case.json
    python scripts/case_envelope.py verify case.json   # 벤더된 검증기 사용

trust 등급 규칙(contracts/trust-levels.md): 파일 해시·크기 같은 기록값만
observed. 모델 점수는 model-assisted. 어댑터가 등급을 올려주지 않는다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
VENDORED_VERIFIER = REPO_ROOT / "contracts" / "verify_contract.py"
VENDORED_SCHEMA = REPO_ROOT / "contracts" / "lazy-evidence-case-v1.json"

_ID_OK = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _eid(raw: str) -> str:
    """경로 등을 스키마의 evidence_id 패턴으로 정규화 (예측 가능하게)."""
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]", ":", str(raw)).strip(":")
    cleaned = re.sub(r":{2,}", ":", cleaned)
    if not cleaned:
        cleaned = hashlib.sha256(str(raw).encode()).hexdigest()[:32]
    return cleaned[:128]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _item(evidence_id, kind, trust, summary, **extra) -> dict:
    item = {
        "evidence_id": _eid(evidence_id),
        "kind": kind,
        "trust": trust,
        "summary": str(summary)[:2000],
    }
    item.update({k: v for k, v in extra.items() if v is not None})
    return item


def _src(path=None, sha256=None, size=None) -> dict | None:
    src = {}
    if path is not None:
        src["path"] = str(path)
    if sha256 is not None and _HEX64.match(str(sha256)):
        src["sha256"] = str(sha256)
    if size is not None:
        try:
            src["size"] = int(size)
        except (TypeError, ValueError):
            pass
    return src or None


def adapt_frametrace(doc: dict) -> list[dict]:
    """package-manifest.json → file items. 해시·크기는 기록값이므로 observed."""
    files = doc.get("files")
    if not isinstance(files, list):
        raise SystemExit("error: frametrace manifest has no 'files' array")
    items = []
    for f in files:
        if not isinstance(f, dict):
            continue
        rel = str(f.get("relative_path", ""))
        items.append(_item(
            f"ft:{rel}", "file", "observed",
            f"FrameTrace package file {rel}",
            source=_src(rel, f.get("sha256"), f.get("size_bytes")),
        ))
    return items


def adapt_rapid(doc: dict) -> list[dict]:
    """rapid results JSON → file items. observed_status는 기록값."""
    rows = doc.get("items")
    if not isinstance(rows, list):
        raise SystemExit("error: rapid results has no 'items' array")
    items = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        rid = str(r.get("item_id") or r.get("normalized_path") or "")
        status = str(r.get("observed_status", "observed"))
        notes = str(r.get("notes", ""))
        items.append(_item(
            f"rapid:{rid}", "file", "observed",
            f"rapid {status}: {r.get('normalized_path', rid)}" + (f" — {notes}" if notes else ""),
            source=_src(r.get("normalized_path"), r.get("sha256"), r.get("size_bytes")),
        ))
    return items


def adapt_deepfake(doc: dict) -> list[dict]:
    """deepfake-lens scan JSON → screening_result. 점수는 model-assisted."""
    rows = doc.get("rows") or doc.get("items") or doc.get("results")
    if isinstance(doc.get("media"), list):
        rows = doc["media"]
    if not isinstance(rows, list):
        rows = [doc] if isinstance(doc, dict) and ("path" in doc or "file" in doc) else []
    if not rows:
        raise SystemExit("error: deepfake scan has no rows/items/results")
    items = []
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            continue
        path = str(r.get("path") or r.get("file") or r.get("name") or f"row-{i}")
        band = r.get("band") or r.get("verdict") or r.get("label") or ""
        score = r.get("score")
        # 스키마 confidence는 0..1. 점수 체계가 다르면(0-100 등) 기록하지 않는다 —
        # 단위를 추측해서 변환하는 것보다 summary에 원값을 보존하는 편이 정직하다.
        confidence = score if isinstance(score, (int, float)) and 0 <= score <= 1 else None
        summary = f"deepfake-lens screening: {path}"
        if band:
            summary += f" [{band}]"
        if score is not None:
            summary += f" score={score}"
        items.append(_item(
            f"df:{path}", "screening_result", "model-assisted",
            summary,
            source=_src(path, r.get("sha256"), r.get("size_bytes")),
            confidence=confidence,
            limitations=["model-assisted score — 독립 대조 없이 단독 판정 근거로 사용 금지"],
        ))
    return items


def adapt_ledger(path: Path) -> list[dict]:
    """audit_ledger JSONL → audit_event items, ledger_ref로 원장과 연결."""
    items = []
    with open(path, "r", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            items.append(_item(
                f"ledger:{i}", "audit_event", "observed",
                f"ledger[{i}] {entry.get('kind', '?')} by {entry.get('actor', '?')}",
                ledger_ref=entry.get("entry_hash"),
            ))
    if not items:
        raise SystemExit("error: ledger file has no parseable entries")
    return items


ADAPTERS = {
    "frametrace": lambda p: adapt_frametrace(_load_json(p)),
    "rapid": lambda p: adapt_rapid(_load_json(p)),
    "deepfake": lambda p: adapt_deepfake(_load_json(p)),
    "ledger": adapt_ledger,
}


def _load_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SystemExit(f"error: cannot read {path}: {e}")


def build(args) -> int:
    items, lineage = [], []
    for spec in args.input:
        if ":" not in spec:
            raise SystemExit(f"error: --input must be producer:path, got {spec!r}")
        producer, p = spec.split(":", 1)
        if producer not in ADAPTERS:
            raise SystemExit(
                f"error: unknown producer {producer!r}; known: {sorted(ADAPTERS)}"
            )
        produced = ADAPTERS[producer](Path(p))
        items.extend(produced)
        for it in produced:
            lineage.append({
                "from_evidence_id": it["evidence_id"],
                "to_evidence_id": args.case_id,
                "relation": "included_in",
                "by_repo": producer,
            })
    if not items:
        raise SystemExit("error: no items produced from inputs")
    doc = {
        "schema_version": "lazy-evidence-case-v1",
        "case_id": args.case_id,
        "created_utc": _utcnow(),
        "producer": {"repo": args.producer_repo, "tool": args.producer_tool},
        "items": items,
        "lineage": lineage,
    }
    out = json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(out + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({len(items)} items)")
    else:
        print(out)
    return 0


def verify(args) -> int:
    """벤더된 contracts/verify_contract.py로 검증 — SSOT 스키마 기준."""
    if not VENDORED_VERIFIER.is_file():
        print("NOT_CHECKED: contracts/verify_contract.py not vendored", file=sys.stderr)
        return 3
    cmd = [sys.executable, str(VENDORED_VERIFIER), str(args.file)]
    if VENDORED_SCHEMA.is_file():
        cmd += ["--schema", str(VENDORED_SCHEMA)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    sys.stdout.write(proc.stdout or "")
    sys.stderr.write(proc.stderr or "")
    return proc.returncode


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="레포 산출물 → case-v1 봉투")
    b.add_argument("--case-id", required=True)
    b.add_argument("--producer-repo", default="lazyforensic")
    b.add_argument("--producer-tool", default="scripts/case_envelope.py")
    b.add_argument("--input", action="append", required=True,
                   help="producer:path — producer ∈ frametrace/rapid/deepfake/ledger")
    b.add_argument("--out", type=Path)
    b.set_defaults(fn=build)

    v = sub.add_parser("verify", help="봉투 스키마 검증 (vendored verifier)")
    v.add_argument("file", type=Path)
    v.set_defaults(fn=verify)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
