from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def verify_audit_chain(trail_path, allow_empty=True, require_hmac=False, hmac_key=None):
    path = Path(trail_path)
    key = os.environ.get("LAZYFORENSIC_HMAC_KEY") if hmac_key is None else hmac_key
    chain_errors, auth_errors = [], []
    verified = 0
    lines = []
    readable = True
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except FileNotFoundError:
        readable = False
        if not allow_empty or require_hmac:
            chain_errors.append("File not found")
    except (OSError, UnicodeError) as exc:
        readable = False
        chain_errors.append(f"Cannot read audit trail: {exc}")
    if not lines and (not allow_empty or require_hmac):
        chain_errors.append("Empty audit trail")
    if require_hmac and not key:
        auth_errors.append("HMAC key not configured")
    previous_hash = None
    previous_timestamp = None
    unsigned = 0
    for index, line in enumerate(lines, 1):
        try:
            entry = json.loads(line)
        except ValueError:
            chain_errors.append(f"Line {index}: Malformed JSON record")
            break
        if not isinstance(entry, dict):
            chain_errors.append(f"Line {index}: Record is not a JSON object")
            break
        for field in ("timestamp", "file"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                chain_errors.append(f"Line {index}: Missing or invalid required field '{field}'")
        try:
            timestamp = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError()
            if previous_timestamp is not None and timestamp < previous_timestamp:
                chain_errors.append(f"Line {index}: Non-monotonic timestamp")
            previous_timestamp = timestamp
        except (KeyError, AttributeError, ValueError, TypeError):
            chain_errors.append(f"Line {index}: Invalid ISO-8601 timestamp")
        if entry.get("prev_hash") != previous_hash:
            chain_errors.append(f"Line {index}: Hash chain broken")
        previous_hash = hashlib.sha256(line.encode("utf-8")).hexdigest()
        signature = entry.get("hmac")
        if not signature:
            unsigned += 1
            if require_hmac:
                auth_errors.append(f"Line {index}: Missing HMAC signature")
        elif key:
            message = "|".join(str(entry.get(k) or "") for k in ("timestamp", "file", "sha256", "prev_hash"))
            expected = hmac.new(key.encode(), message.encode(), hashlib.sha256).hexdigest()
            if isinstance(signature, str) and hmac.compare_digest(expected, signature):
                verified += 1
            else:
                auth_errors.append(f"Line {index}: HMAC verification failed")
    errors = chain_errors + auth_errors
    chain_status = "failed" if chain_errors else ("verified" if lines else "not_measured")
    authenticated = bool(lines) and verified == len(lines) and not errors
    return {
        "status": "FAIL" if errors else "PASS", "file": str(path),
        "total_records": len(lines), "valid_chain": chain_status == "verified",
        "chain_status": chain_status, "authenticated": authenticated,
        "authentication_status": "failed" if auth_errors else ("verified" if authenticated else "not_measured"),
        "unsigned_records": unsigned, "verified_signatures": verified,
        "message": "Audit verification failed" if errors else ("Linked records verified" if lines else "No records measured"),
        "errors": errors,
        "limitations": ["Local chain verification is not independent custody or completeness certification",
                        "Legacy HMAC authenticates timestamp, file, sha256 and prev_hash only"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify audit chain and optional HMAC authentication")
    parser.add_argument("trail", nargs="?", default=".lazyforensic/audit_trail.jsonl")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-empty", action="store_true")
    parser.add_argument("--require-hmac", action="store_true")
    args = parser.parse_args(argv)
    result = verify_audit_chain(args.trail, not args.no_empty, args.require_hmac)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"[{result['status']}] {result['message']}")
        for error in result["errors"]:
            print(error, file=sys.stderr)
    return int(result["status"] == "FAIL")


if __name__ == "__main__":
    sys.exit(main())
