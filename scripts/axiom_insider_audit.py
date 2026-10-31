#!/usr/bin/env python3
"""AXIOM 10.x (scan_artifact_hit) 심층 검증·집계·.git 원격푸시/로컬커밋 분리·배임 프롬프트 스캐너."""
from __future__ import annotations

import datetime as _dt
import os
import re
import sqlite3
from collections import defaultdict

KST = _dt.timezone(_dt.timedelta(hours=9))

INSIDER_PROMPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "withholding_breach": re.compile(
        r"안\s*나가게|넘어가지\s*않게|내부\s*발신|발신본|로직.*(?:빼|제거|지워)|"
        r"주석.*(?:빼|제거|지워)|하드코딩|독립\s*개발\s*공간", re.IGNORECASE),
    "memory_suppression": re.compile(
        r"메모리에\s*적지|메모리에서\s*(?:삭제|지워)|기록하지\s*마|기억하지\s*마|흔적.*지워", re.IGNORECASE),
    "git_batch_exfil": re.compile(
        r"커밋하고\s*푸[쉬시]|전부\s*푸[쉬시]|범위\s*밖|원격.*푸[쉬시]", re.IGNORECASE),
    "side_business_publish": re.compile(
        r"마켓플레이스|학회|논문\s*접수|외주|숨고|대학원", re.IGNORECASE),
    "identity_attribution": re.compile(
        r"[가-힣]{2,4}님\s*(?:승인|관찰|답\s*원문|지시)", re.IGNORECASE),
}


def has_axiom_v10_schema(conn: sqlite3.Connection) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='scan_artifact_hit'"
    ).fetchone() is not None

def get_axiom_canonical_artifacts(conn: sqlite3.Connection) -> list[str]:
    sql = (
        "SELECT DISTINCT artifact_name FROM artifact_version WHERE artifact_name IS NOT NULL"
        if has_axiom_v10_schema(conn)
        else "SELECT DISTINCT name FROM artifact WHERE name IS NOT NULL"
    )
    return [str(r[0]) for r in conn.execute(sql).fetchall() if str(r[0]).strip()]

def fetch_axiom_v10_hits(conn: sqlite3.Connection, hit_ids: list[int]) -> dict[int, dict]:
    """AXIOM 10.x scan_artifact_hit 스키마에서 hit_id별 아티팩트명·위치·핵심 fragment를 조회한다."""
    if not hit_ids:
        return {}
    uniq = sorted({int(x) for x in hit_ids if int(x) > 0})
    out: dict[int, dict] = {}
    for i in range(0, len(uniq), 400):
        chunk = uniq[i : i + 400]
        ph = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"SELECT sh.hit_id, av.artifact_name, hl.source_id, hl.location_value, hl.deleted_source_file "
            f"FROM scan_artifact_hit sh JOIN artifact_version av ON sh.artifact_version_id = av.artifact_version_id "
            f"LEFT JOIN hit_location hl ON sh.hit_id = hl.hit_id AND hl.sort_order = 0 WHERE sh.hit_id IN ({ph})",
            chunk,
        ).fetchall()
        for hid, aname, sid, loc, deleted in rows:
            out[int(hid)] = {
                "hit_id": int(hid), "source_id": int(sid) if sid is not None else None,
                "location": str(loc or ""), "deleted": int(deleted or 0),
                "artifact_name": str(aname), "fragments": {},
            }
        for sql in (
            f"SELECT s.hit_id, fd.name, COALESCE(fc.content, s.value) FROM hit_fragment_string s "
            f"JOIN fragment_definition fd ON s.fragment_definition_id = fd.fragment_definition_id "
            f"LEFT JOIN fragment_content fc ON s.hit_fragment_id = fc.hit_fragment_id WHERE s.hit_id IN ({ph})",
            f"SELECT d.hit_id, fd.name, d.formatted_value FROM hit_fragment_date d "
            f"JOIN fragment_definition fd ON d.fragment_definition_id = fd.fragment_definition_id WHERE d.hit_id IN ({ph})",
            f"SELECT iv.hit_id, fd.name, CAST(iv.value AS TEXT) FROM hit_fragment_int iv "
            f"JOIN fragment_definition fd ON iv.fragment_definition_id = fd.fragment_definition_id WHERE iv.hit_id IN ({ph})",
        ):
            for hid, fname, fval in conn.execute(sql, chunk).fetchall():
                ihid = int(hid)
                if ihid in out and fval is not None and str(fval).strip():
                    frags = out[ihid]["fragments"]
                    if len(frags) < 8 and str(fname) not in frags:
                        frags[str(fname)] = str(fval).replace("\r", " ").replace("\n", " ")[:140]
    return out


def export_axiom_counts(conn: sqlite3.Connection, out_dir: str) -> list[tuple[str, int]]:
    """Case.mfdb 내 전체 아티팩트별 hit 건수를 집계하여 artifact_counts.txt로 저장한다."""
    os.makedirs(out_dir, exist_ok=True)
    sql = (
        "SELECT av.artifact_name, COUNT(*) AS cnt FROM scan_artifact_hit sh "
        "JOIN artifact_version av ON sh.artifact_version_id = av.artifact_version_id "
        "GROUP BY av.artifact_name ORDER BY cnt DESC, av.artifact_name ASC"
        if has_axiom_v10_schema(conn)
        else "SELECT a.name, COUNT(*) AS cnt FROM hit h JOIN artifact_version av ON h.artifact_version_id = av.id "
        "JOIN artifact a ON av.artifact_id = a.id GROUP BY a.name ORDER BY cnt DESC, a.name ASC"
    )
    result = [(str(name), int(cnt)) for name, cnt in conn.execute(sql).fetchall() if name]
    with open(os.path.join(out_dir, "artifact_counts.txt"), "w", encoding="utf-8") as f:
        for name, cnt in result:
            f.write(f"{name}\t{cnt}\n")
    return result


def scan_insider_prompts(conn: sqlite3.Connection) -> dict:
    """Claude Command History 등에서 업무상 배임(코드 은폐·제거)·메모리 삭제·일괄 푸시 지시를 탐지한다."""
    rows: list[tuple[int, str, str]] = []
    if has_axiom_v10_schema(conn):
        raw = conn.execute(
            "SELECT sh.hit_id, fd.name, COALESCE(fc.content, s.value) FROM scan_artifact_hit sh "
            "JOIN artifact_version av ON sh.artifact_version_id = av.artifact_version_id "
            "JOIN hit_fragment_string s ON sh.hit_id = s.hit_id "
            "JOIN fragment_definition fd ON s.fragment_definition_id = fd.fragment_definition_id "
            "LEFT JOIN fragment_content fc ON s.hit_fragment_id = fc.hit_fragment_id "
            "WHERE av.artifact_name LIKE '%Claude Command History%' OR av.artifact_name LIKE '%Prompt%'"
        ).fetchall()
        by_hit: dict[int, dict[str, str]] = defaultdict(dict)
        for hid, fname, val in raw:
            if val:
                by_hit[int(hid)][str(fname)] = str(val)
        for hid, fmap in sorted(by_hit.items()):
            msg = fmap.get("Message Content") or fmap.get("Command") or " ".join(fmap.values())
            rows.append((hid, fmap.get("File Path", ""), msg))
    else:
        raw = conn.execute(
            "SELECT h.id, hf.name, hf.value FROM hit h JOIN artifact_version av ON h.artifact_version_id = av.id "
            "JOIN artifact a ON av.artifact_id = a.id JOIN hit_fragment hf ON h.id = hf.hit_id "
            "WHERE a.name LIKE '%Claude Command History%' OR a.name LIKE '%Prompt%'"
        ).fetchall()
        rows = [(int(hid), "", str(val)) for hid, _fname, val in raw if val]

    findings: dict[str, list[dict]] = {k: [] for k in INSIDER_PROMPT_PATTERNS}
    for hid, path, msg in rows:
        for cat, rx in INSIDER_PROMPT_PATTERNS.items():
            if rx.search(msg):
                findings[cat].append({
                    "hit_id": hid, "path": path,
                    "snippet": msg.replace("\r", " ").replace("\n", " ")[:180],
                })
    return {
        "total_prompts_scanned": len(rows),
        "category_counts": {k: len(v) for k, v in findings.items()},
        "findings": findings,
    }


_REFLOG_LINE_RE = re.compile(
    r"^([0-9a-f]{40})\s+([0-9a-f]{40})\s+(.+?)\s+<([^>]+)>\s+(\d+)\s+([+-]\d{4})\t(.*)$"
)
_REMOTE_URL_RE = re.compile(r"^\s*url\s*=\s*(.+)$", re.MULTILINE)

def decode_smart_text(raw: bytes) -> tuple[str, str]:
    """UTF-16 (LE/BE BOM 및 PowerShell 무-BOM UTF-16LE) 및 UTF-8 텍스트를 자동 복원한다."""
    if raw.startswith(b"\xff\xfe"):
        return raw.decode("utf-16-le", errors="replace").lstrip("\ufeff"), "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16-be", errors="replace").lstrip("\ufeff"), "utf-16-be"
    if len(raw) >= 4 and raw[1:4:2] == b"\x00\x00":
        return raw.decode("utf-16-le", errors="replace"), "utf-16-le-nobom"
    return raw.decode("utf-8-sig", errors="replace"), "utf-8"

def _parse_reflog_text(text: str) -> list[dict]:
    entries: list[dict] = []
    for line in text.splitlines():
        m = _REFLOG_LINE_RE.match(line.strip())
        if not m:
            continue
        old_sha, new_sha, author, email, epoch_s, tz_s, action = m.groups()
        epoch = int(epoch_s)
        dt_kst = _dt.datetime.fromtimestamp(epoch, tz=KST).strftime("%Y-%m-%d %H:%M:%S KST")
        entries.append({
            "old_sha": old_sha, "new_sha": new_sha, "author": author, "email": email,
            "epoch": epoch, "timestamp_kst": dt_kst, "tz": tz_s, "action": action.strip(),
        })
    return entries

def scan_git_and_utf16(root_path: str) -> dict:
    """디렉터리 내 원본 .git 저장소(원격 푸시 vs 로컬 커밋 엄격 분리) 및 UTF-16 덤프를 전수 스캔한다."""
    repos: list[dict] = []
    utf16_files: list[dict] = []
    all_pushes: list[dict] = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        if os.path.basename(dirpath) == ".git":
            repo_root = os.path.dirname(dirpath)
            cfg_path = os.path.join(dirpath, "config")
            remotes: list[str] = []
            if os.path.isfile(cfg_path):
                with open(cfg_path, "rb") as f:
                    cfg_txt, _ = decode_smart_text(f.read())
                remotes = [m.group(1).strip() for m in _REMOTE_URL_RE.finditer(cfg_txt)]
            pushes: list[dict] = []
            remotes_dir = os.path.join(dirpath, "logs", "refs", "remotes")
            if os.path.isdir(remotes_dir):
                for rdp, _, rfiles in os.walk(remotes_dir):
                    for rf in rfiles:
                        with open(os.path.join(rdp, rf), "rb") as f:
                            txt, _ = decode_smart_text(f.read())
                        for ent in _parse_reflog_text(txt):
                            ent["repo"] = repo_root
                            pushes.append(ent)
                            all_pushes.append(ent)
            commits: list[dict] = []
            head_log = os.path.join(dirpath, "logs", "HEAD")
            if os.path.isfile(head_log):
                with open(head_log, "rb") as f:
                    txt, _ = decode_smart_text(f.read())
                commits = [e for e in _parse_reflog_text(txt) if e["action"].startswith("commit")]
            pushes.sort(key=lambda x: x["epoch"])
            commits.sort(key=lambda x: x["epoch"])
            last_push_ep = pushes[-1]["epoch"] if pushes else 0
            unpushed = [c for c in commits if c["epoch"] > last_push_ep]
            repos.append({
                "repo_path": repo_root, "remotes": remotes,
                "remote_push_count": len(pushes), "local_commit_count": len(commits),
                "first_push_kst": pushes[0]["timestamp_kst"] if pushes else None,
                "last_push_kst": pushes[-1]["timestamp_kst"] if pushes else None,
                "last_local_commit_kst": commits[-1]["timestamp_kst"] if commits else None,
                "unpushed_local_commits": len(unpushed),
            })
            dirnames[:] = []
            continue
        for fn in filenames:
            if fn.lower().endswith((".txt", ".log", ".tsv")):
                fpath = os.path.join(dirpath, fn)
                try:
                    with open(fpath, "rb") as f:
                        raw = f.read(4_000_000)
                except OSError:
                    continue
                txt, enc = decode_smart_text(raw)
                if enc.startswith("utf-16"):
                    lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
                    utf16_files.append({
                        "file": fpath, "encoding": enc, "line_count": len(lines),
                        "received_04_count": sum(1 for ln in lines if "04_received" in ln.lower()),
                    })
    all_pushes.sort(key=lambda x: x["epoch"])
    bursts: list[dict] = []
    for i, p in enumerate(all_pushes):
        win = [x for x in all_pushes[i:] if x["epoch"] - p["epoch"] <= 60]
        uniq_repos = sorted({x["repo"] for x in win})
        if len(uniq_repos) >= 3:
            bursts.append({
                "start_kst": win[0]["timestamp_kst"], "end_kst": win[-1]["timestamp_kst"],
                "duration_sec": win[-1]["epoch"] - win[0]["epoch"],
                "repo_count": len(uniq_repos), "push_count": len(win),
            })
            break
    return {
        "repo_count": len(repos),
        "total_remote_pushes": sum(r["remote_push_count"] for r in repos),
        "total_local_commits": sum(r["local_commit_count"] for r in repos),
        "batch_push_bursts": bursts, "repos": repos, "utf16_files": utf16_files,
    }
