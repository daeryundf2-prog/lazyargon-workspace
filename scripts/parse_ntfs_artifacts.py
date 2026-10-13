#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_ntfs_artifacts.py - Dissect 기반 디스크 이미지 및 NTFS/아티팩트 무설치 파서

Fail-closed 규약: Dissect 미설치/Target.open 실패/질의 오류는 '레코드 0건'이 아니라
error 필드 + 0이 아닌 exit 코드(3)로 보고한다. 포렌식 도구가 파싱 실패를
"prefetch 없음"으로 위장하면 보고서가 거짓 결론을 근거하게 된다.
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MAX_RECORDS_DEFAULT = 10000


def run_dissect_query(target_path: str, artifact_type: str, limit: int = MAX_RECORDS_DEFAULT):
    """Fox-IT Dissect 프레임워크를 활용한 아티팩트 추출 (bring-your-own-binary 래퍼).
    E01/RAW는 dissect + ewf 플러그인 필요.
    반환: (records, error) — error 는 None 또는 사람이 읽을 수 있는 실패 사유.
    """
    try:
        from dissect.target import Target
    except ImportError:
        return [], (
            "Dissect 프레임워크 미설치 — pip install dissect[full] 실행 후 재시도. "
            "이 상태에서는 레코드 0건조차 보고할 수 없다."
        )

    # E01 사전 힌트
    lower = target_path.lower()
    if lower.endswith(('.e01', '.ex01', '.e0')):
        print("[i] E01 감지: ewf/ewf-mount 플러그인이 필요할 수 있습니다. dissect.volume.ewf 확인.", file=sys.stderr)

    results = []
    target = None
    try:
        # Target.open 은 디렉토리/마운트 경로와 일부 이미지를 처리. E01은 플러그인 없으면 예외.
        target = Target.open(target_path)
    except Exception as e:
        return [], (
            f"Dissect Target.open 실패 on '{target_path}': {e}. "
            "이미지가 E01이면 ewfmount 후 마운트 경로를 전달하거나 dissect[full] 설치 확인."
        )

    truncated = False
    try:
        if artifact_type == "users":
            for user in target.users():
                results.append({
                    "username": getattr(user, "name", "N/A"),
                    "home": getattr(user, "home", "N/A"),
                    "sid": getattr(user, "sid", "N/A")
                })
                if len(results) >= limit:
                    truncated = True
                    break
        elif artifact_type == "prefetch":
            func = getattr(target, "prefetch", None)
            if func is None:
                return [], "target.prefetch() 미지원 Dissect 버전 — dissect.target 3.15+ 권장"
            for pf in func():
                results.append({
                    "executable": getattr(pf, "name", getattr(pf, "executable", "N/A")),
                    "run_count": getattr(pf, "run_count", 0),
                    "last_run": str(getattr(pf, "last_run", getattr(pf, "last_execution", "N/A")))
                })
                if len(results) >= limit:
                    truncated = True
                    break
        elif artifact_type == "eventlogs":
            func = getattr(target, "eventlogs", None)
            if func is None:
                return [], "target.eventlogs() 미지원 — 대신 Hayabusa/Chainsaw로 .evtx 직접 분석 권장"
            for record in func():
                # event_id 접근은 단일 getattr 로 통일 (구버전은 같은 속성을 두 번 물어보는 복붙 버그)
                results.append({
                    "timestamp": str(getattr(record, "ts", getattr(record, "timestamp", "N/A"))),
                    "provider": getattr(record, "provider", getattr(record, "source", "N/A")),
                    "event_id": getattr(record, "event_id", "N/A"),
                    "computer": getattr(record, "computer", "N/A")
                })
                if len(results) >= limit:
                    truncated = True
                    break
        elif artifact_type == "shimcache":
            func = getattr(target, "shimcache", None)
            if func is None:
                return [], "target.shimcache() 미지원 Dissect 버전"
            for shim in func():
                results.append({
                    "path": getattr(shim, "path", "N/A"),
                    "last_modified": str(getattr(shim, "last_modified", "N/A")),
                    "exec_flag": getattr(shim, "exec_flag", "N/A")
                })
                if len(results) >= limit:
                    truncated = True
                    break
    except Exception as e:
        return results, f"Dissect query error on '{target_path}' artifact '{artifact_type}': {e}"
    finally:
        try:
            if target is not None and hasattr(target, "close"):
                target.close()
        except Exception:
            pass

    return results, None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fox-IT Dissect 기반 디스크 아티팩트 파서")
    parser.add_argument("target", help="분석 대상 디스크 이미지 (E01, RAW, VHDX, VMDK) 또는 루트 경로")
    parser.add_argument("--artifact", "-a", choices=["users", "prefetch", "eventlogs", "shimcache"], default="prefetch", help="추출할 아티팩트 유형")
    parser.add_argument("--output", "-o", help="결과 JSON 저장 경로")
    parser.add_argument("--limit", type=int, default=MAX_RECORDS_DEFAULT,
                        help=f"레코드 상한 (기본 {MAX_RECORDS_DEFAULT}) — eventlogs 등 대용량 이터레이션 보호")
    args = parser.parse_args(argv)

    if not os.path.exists(args.target):
        print(f"Error: Target not found: {args.target}", file=sys.stderr)
        return 1

    # 진행 로그는 stderr 로 — stdout 은 JSON 데이터 전용으로 유지한다.
    print(f"[*] Extracting artifact '{args.artifact}' from '{args.target}'...", file=sys.stderr)
    data, error = run_dissect_query(args.target, args.artifact, limit=max(1, args.limit))

    output_json = {
        "target": args.target,
        "artifact": args.artifact,
        "count": len(data),
        "error": error,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "records": data,
    }

    if error:
        # 실패를 성공처럼 쓰지 않는다: error 필드가 담긴 JSON + exit 3.
        print(json.dumps(output_json, ensure_ascii=False, indent=2))
        print(f"[FAIL] {error}", file=sys.stderr)
        return 3

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_json, f, ensure_ascii=False, indent=2)
        print(f"[OK] Saved {len(data)} records to: {args.output}")
    else:
        print(json.dumps(output_json, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
