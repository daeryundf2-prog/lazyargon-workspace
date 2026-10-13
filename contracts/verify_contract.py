#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_contract.py — lazy-evidence-case-v1 산출물 검증기 (의존성 0)

jsonschema 외부 패키지 없이 이 스키마가 쓰는 키워드만 검증한다:
type, required, properties, additionalProperties, const, enum, pattern,
format(date-time), minimum/maximum, minItems, maxLength, items, $ref(#/$defs/*)

사용:
    python scripts/verify_contract.py case.json
    python scripts/verify_contract.py case.json --schema schemas/lazy-evidence-case-v1.json
    python scripts/verify_contract.py --drift-check <vendored_schema>  # SSOT 해시 대조
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA = ROOT / "schemas" / "lazy-evidence-case-v1.json"

_TYPE_MAP = {
    "object": dict, "array": list, "string": str,
    "integer": int, "number": (int, float), "boolean": bool,
}


def _err(errors: list, path: str, msg: str) -> None:
    errors.append(f"{path or '$'}: {msg}")


def _check_format(value, fmt, path, errors):
    if fmt == "date-time":
        try:
            datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            _err(errors, path, f"date-time 형식 아님: {value!r}")


def _validate(node, schema, defs, path, errors):
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        ref = schema["$ref"]
        if ref.startswith("#/$defs/"):
            schema = defs.get(ref.split("/")[-1], {})
        else:
            _err(errors, path, f"지원하지 않는 $ref: {ref}")
            return
    if "const" in schema and node != schema["const"]:
        _err(errors, path, f"const 불일치: {node!r} != {schema['const']!r}")
        return
    if "enum" in schema and node not in schema["enum"]:
        _err(errors, path, f"enum 위반: {node!r} not in {schema['enum']}")
        return
    t = schema.get("type")
    if t:
        expected = _TYPE_MAP.get(t)
        if expected and not isinstance(node, expected):
            _err(errors, path, f"type 불일치: 기대 {t}, 실제 {type(node).__name__}")
            return
        if t == "integer" and isinstance(node, bool):
            _err(errors, path, "bool은 integer가 아님")
            return
    if isinstance(node, dict):
        for req in schema.get("required", []):
            if req not in node:
                _err(errors, path, f"required 누락: {req}")
        props = schema.get("properties", {})
        for k, v in node.items():
            if k in props:
                _validate(v, props[k], defs, f"{path}.{k}", errors)
            elif schema.get("additionalProperties") is False:
                _err(errors, path, f"허용되지 않은 속성: {k}")
    elif isinstance(node, list):
        if "minItems" in schema and len(node) < schema["minItems"]:
            _err(errors, path, f"minItems 위반: {len(node)}")
        for i, item in enumerate(node):
            _validate(item, schema.get("items", {}), defs, f"{path}[{i}]", errors)
    elif isinstance(node, str):
        if "pattern" in schema and not re.fullmatch(schema["pattern"], node):
            _err(errors, path, f"pattern 불일치: {node!r}")
        if "maxLength" in schema and len(node) > schema["maxLength"]:
            _err(errors, path, f"maxLength 초과: {len(node)}")
        if "format" in schema:
            _check_format(node, schema["format"], path, errors)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        if "minimum" in schema and node < schema["minimum"]:
            _err(errors, path, f"minimum 위반: {node}")
        if "maximum" in schema and node > schema["maximum"]:
            _err(errors, path, f"maximum 위반: {node}")


def validate(doc: dict, schema: dict) -> list[str]:
    errors: list[str] = []
    _validate(doc, schema, schema.get("$defs", {}), "", errors)
    return errors


def drift_check(vendored: Path, canonical: Path = DEFAULT_SCHEMA) -> bool:
    """벤더된 스키마가 SSOT와 동일한지 SHA-256으로 대조한다."""
    if not vendored.exists():
        print(f"벤더 파일 없음: {vendored}", file=sys.stderr)
        return False
    v_bytes = vendored.read_bytes()
    c_bytes = canonical.read_bytes()
    v = hashlib.sha256(v_bytes).hexdigest()
    c = hashlib.sha256(c_bytes).hexdigest()
    if v != c:
        hint = ""
        if hashlib.sha256(v_bytes.replace(b"\r\n", b"\n")).hexdigest() == c:
            hint = ("\n  진단: CRLF 줄바꿈 변환이 감지됐습니다 — 체크아웃 시 "
                    "git이 바이트를 바꿨습니다.\n  .gitattributes에 "
                    "`contracts/** -text`를 추가하고 파일을 다시 체크아웃하세요.")
        elif b"\r\n" in v_bytes or b"\r\n" in c_bytes:
            hint = ("\n  진단: 한쪽 파일에 CRLF가 있습니다 — 해시 외에 "
                    "줄바꿈 변환 여부를 확인하세요.")
        print(f"DRIFT: {vendored} != {canonical}\n  vendored={v}\n  canonical={c}{hint}",
              file=sys.stderr)
        return False
    print(f"OK — {vendored.name}이 SSOT와 동일 ({v[:16]}…)")
    return True


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="lazy-evidence-case-v1 검증기")
    ap.add_argument("doc", nargs="?", help="검증할 JSON 산출물")
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    ap.add_argument("--drift-check", type=Path, default=None,
                    help="벤더된 스키마와 SSOT의 해시 대조")
    args = ap.parse_args(argv)

    if args.drift_check is not None:
        return 0 if drift_check(args.drift_check) else 1
    if not args.doc:
        ap.error("doc 또는 --drift-check 중 하나는 필요합니다")

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    doc = json.loads(Path(args.doc).read_text(encoding="utf-8"))
    errors = validate(doc, schema)
    if errors:
        for e in errors:
            print(f"FAIL {e}", file=sys.stderr)
        return 1
    print(f"OK — {args.doc} conforms to {schema.get('$id', 'schema')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
