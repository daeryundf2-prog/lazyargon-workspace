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
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

MAX_RECORDS_DEFAULT = 10000

def _wevtutil_eventlogs(target_path: str, limit: int = MAX_RECORDS_DEFAULT):
    import shutil
    import subprocess
    import xml.etree.ElementTree as ET
    if os.name != "nt" or not shutil.which("wevtutil.exe"):
        return None
    evtx_files = []
    if os.path.isfile(target_path) and target_path.lower().endswith(".evtx"):
        evtx_files.append(target_path)
    elif os.path.isdir(target_path):
        for root_d, _, fnames in os.walk(target_path):
            for fn in sorted(fnames):
                if fn.lower().endswith(".evtx"):
                    evtx_files.append(os.path.join(root_d, fn))
    if not evtx_files:
        return None
    records = []
    for evtx in evtx_files:
        rem = max(1, limit - len(records))
        proc = subprocess.run(
            ["wevtutil.exe", "qe", evtx, "/lf:true", "/f:xml", f"/c:{rem}"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            continue
        xml_wrapped = "<Events>" + proc.stdout + "</Events>"
        try:
            root = ET.fromstring(xml_wrapped)
        except ET.ParseError:
            continue
        ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
        for ev in root.findall("e:Event", ns):
            sys_el = ev.find("e:System", ns)
            if sys_el is None:
                continue
            prov_el = sys_el.find("e:Provider", ns)
            eid_el = sys_el.find("e:EventID", ns)
            tc_el = sys_el.find("e:TimeCreated", ns)
            comp_el = sys_el.find("e:Computer", ns)
            chan_el = sys_el.find("e:Channel", ns)
            records.append({
                "timestamp": tc_el.attrib.get("SystemTime", "N/A") if tc_el is not None else "N/A",
                "provider": prov_el.attrib.get("Name", "N/A") if prov_el is not None else "N/A",
                "event_id": int(eid_el.text) if (eid_el is not None and eid_el.text and eid_el.text.isdigit()) else (eid_el.text if eid_el is not None else "N/A"),
                "computer": comp_el.text if comp_el is not None else "N/A",
                "channel": chan_el.text if chan_el is not None else "N/A",
                "source_file": os.path.basename(evtx),
            })
            if len(records) >= limit:
                return records
    return records



def _plain(v):
    """Dissect 레코드 값(windows_path, datetime 등)을 JSON 에 쓸 수 있는 값으로."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    return str(v)


def _fields(record) -> dict[str, Any]:
    raw = record._asdict() if hasattr(record, "_asdict") else {}
    return {k: _plain(v) for k, v in raw.items() if not k.startswith("_")}


def _evtx_files(target_path: str) -> list[str]:
    if os.path.isfile(target_path):
        return [target_path] if target_path.lower().endswith(".evtx") else []
    if not os.path.isdir(target_path) or os.path.isdir(os.path.join(target_path, "Windows")):
        return []
    out = []
    for root_d, _, fnames in os.walk(target_path):
        out += [os.path.join(root_d, fn) for fn in sorted(fnames) if fn.lower().endswith(".evtx")]
    return out


def _direct_evtx(files: list[str], limit: int):
    """내보낸 .evtx 파일(또는 그 폴더)을 OS 이미지 없이 dissect.eventlog 로 직접 읽는다."""
    try:
        from dissect.eventlog import evtx
    except ImportError:
        return [], "dissect.eventlog 미설치 — pip install dissect.eventlog 또는 Hayabusa/Chainsaw 사용"
    core = {"TimeCreated_SystemTime", "Provider_Name", "EventID", "Computer", "Channel", "EventRecordID"}
    records: list[dict[str, Any]] = []
    for path in files:
        try:
            with open(path, "rb") as fh:
                for ev in evtx.Evtx(fh):
                    as_dict = getattr(ev, "_asdict", None)
                    f = {k: _plain(v) for k, v in (as_dict() if as_dict else dict(ev.items())).items()}
                    records.append({
                        "timestamp": f.get("TimeCreated_SystemTime"),
                        "provider": f.get("Provider_Name"),
                        "event_id": f.get("EventID"),
                        "channel": f.get("Channel"),
                        "computer": f.get("Computer"),
                        "record_id": f.get("EventRecordID"),
                        "source_file": os.path.basename(path),
                        "data": {k: v for k, v in f.items() if k not in core and v not in (None, "", "None")},
                    })
                    if len(records) >= limit:
                        return records, None
        except Exception as e:
            return records, f"EVTX 파싱 실패 '{path}': {e}"
    return records, None


def run_dissect_query(target_path: str, artifact_type: str, limit: int = MAX_RECORDS_DEFAULT):
    """Fox-IT Dissect 프레임워크를 활용한 아티팩트 추출 (bring-your-own-binary 래퍼).
    E01/RAW는 dissect + ewf 플러그인 필요.
    반환: (records, error) — error 는 None 또는 사람이 읽을 수 있는 실패 사유.
    """
    try:
        from dissect.target import Target
    except ImportError:
        if artifact_type == "eventlogs":
            fb = _wevtutil_eventlogs(target_path, limit=limit)
            if fb is not None:
                return fb, None
        return [], (
            "Dissect 프레임워크 미설치 — pip install dissect[full] 실행 후 재시도. "
            "이 상태에서는 레코드 0건조차 보고할 수 없다."
        )

    if artifact_type == "eventlogs":
        files = _evtx_files(target_path)
        if files:
            return _direct_evtx(files, limit)

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
                f = _fields(user)
                results.append({"username": f.get("name"), "home": f.get("home"), "sid": f.get("sid")})
                if len(results) >= limit:
                    truncated = True
                    break
        elif artifact_type == "prefetch":
            func = getattr(target, "prefetch", None)
            if func is None:
                return [], "target.prefetch() 미지원 Dissect 버전 — dissect.target 3.15+ 권장"
            # Dissect 는 .pf 하나를 '실행 시각 × 참조 파일' 행으로 펼친다. 행 수를 실행 횟수로 보고하지 않도록 .pf 단위로 묶는다.
            by_pf: dict[str, dict[str, Any]] = {}
            for pf in func():
                f = _fields(pf)
                key = str(f.get("prefetch") or f.get("filename") or "unknown")
                entry = by_pf.setdefault(key, {"executable": f.get("filename"), "prefetch_file": f.get("prefetch"),
                                               "run_count": f.get("runcount"), "run_times": set(), "linked_files": set()})
                if f.get("ts"):
                    entry["run_times"].add(f["ts"])
                if f.get("linkedfile"):
                    entry["linked_files"].add(f["linkedfile"])
                if len(by_pf) > limit:
                    truncated = True
                    break
            for entry in list(by_pf.values())[:limit]:
                times = sorted(entry.pop("run_times"))
                entry["last_run"] = times[-1] if times else None
                entry["run_times"] = times
                entry["linked_file_count"] = len(entry.pop("linked_files"))
                results.append(entry)
        elif artifact_type == "eventlogs":
            func = getattr(target, "evtx", None) if target.has_function("evtx") else None
            if func is None:
                return [], "target.evtx() 미지원 — 대신 Hayabusa/Chainsaw로 .evtx 직접 분석 권장"
            for record in func():
                f = _fields(record)
                core = {"ts", "Provider_Name", "EventID", "Computer", "Channel", "EventRecordID", "hostname", "domain"}
                results.append({
                    "timestamp": f.get("ts"),
                    "provider": f.get("Provider_Name"),
                    "event_id": f.get("EventID"),
                    "channel": f.get("Channel"),
                    "computer": f.get("Computer"),
                    "record_id": f.get("EventRecordID"),
                    "data": {k: v for k, v in f.items() if k not in core and v not in (None, "", "None")},
                })
                if len(results) >= limit:
                    truncated = True
                    break
        elif artifact_type == "shimcache":
            func = getattr(target, "shimcache", None)
            if func is None:
                return [], "target.shimcache() 미지원 Dissect 버전"
            for shim in func():
                f = _fields(shim)
                rec = {"path": f.get("path"), "last_modified": f.get("last_modified"),
                       "cache_name": f.get("name"), "index": f.get("index")}
                # 경로가 비었거나 '.'이고 시각이 1601년(파일타임 0 근처)이면 파서가 항목을 해석하지 못한 것이다.
                if str(rec["path"] or "").strip(". ") == "" or str(rec["last_modified"] or "").startswith("1601-"):
                    rec["suspect"] = "경로 없음 또는 1601년 시각 — 해석 실패 가능성. 다른 도구(AppCompatCacheParser 등)로 교차 확인 전에는 근거로 쓰지 말 것"
                results.append(rec)
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
        print(json.dumps(output_json, ensure_ascii=False, indent=2, default=str))
        print(f"[FAIL] {error}", file=sys.stderr)
        return 3

    if args.output:
        text = json.dumps(output_json, ensure_ascii=False, indent=2, default=str)
        tmp = args.output + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, args.output)
        print(f"[OK] Saved {len(data)} records to: {args.output}")
    else:
        print(json.dumps(output_json, ensure_ascii=False, indent=2))
    return 0


def _reexec_in_plugin_venv() -> None:
    """Dissect 가 없는 python 으로 실행되면 플러그인 .venv 의 python 으로 다시 실행한다."""
    try:
        import dissect.target  # noqa: F401
        return
    except ImportError:
        pass
    venv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".venv")
    if os.path.realpath(sys.prefix) == os.path.realpath(venv):
        return
    for cand in (os.path.join(venv, "bin", "python"), os.path.join(venv, "Scripts", "python.exe")):
        if os.path.exists(cand):
            os.execv(cand, [cand, os.path.abspath(__file__), *sys.argv[1:]])


if __name__ == "__main__":
    _reexec_in_plugin_venv()
    sys.exit(main())
