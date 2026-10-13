#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
case_survey.py — 증거 디렉터리 통합 선조사 파이프라인

의뢰인 데이터 폴더 하나를 던지면 이 레포의 결정적 도구들을 순서대로
돌려 단일 리포트를 만든다. 각 단계는 독립적이라 하나가 실패해도
나머지는 계속되고, 실패는 '생략'이 아니라 '실패'로 기록된다.

실행 순서:
    1. evidence_manifest  — 전체 파일 해시 매니페스트 (변경 탐지 기준)
    2. pii_mask (탐지만)  — 외부 공유 전 알아야 할 개인정보 분포
    3. keyword_report     --keywords 지정 시
    4. audio_survey       — 발화 구간 후보 지도
    5. exif_audit         — 이미지 메타데이터 (Pillow 필요)
    6. image_similarity   — 유사 이미지 쌍 (Pillow 필요)
    7. signature_check    — 확장자 vs 매직바이트 위장 감사
    8. dedup_files        — 정확 중복 + 유사 이미지 그룹
    9. archive_survey     — zip/tar 내부 위장·암호화 멤버 (추출 없이)
   10. pdf_audit          — PDF 암호화·능동 콘텐츠·메타데이터
   11. sqlite_survey      — SQLite DB 스키마·행 수·무결성 (읽기 전용)
   12. video_fingerprint  — 영상 지문 목록 (ffmpeg 필요)
   13. video_integrity    — 영상 손상·잘림 감지 (ffmpeg 필요)
   14. audio_fingerprint  — 오디오 내용 지문 유사 쌍 (fpcalc 필요)
   15. local_stt          --stt 지정 시 (로컬 엔진 필요)

스키마 계약 (survey_version):
    리포트 JSON의 survey_version은 단계 구성이 바뀔 때 올라간다.
    소비자는 모르는 steps 키를 무시해야 하고, 각 단계의 status가
    'ok'가 아니면 result 대신 error/stderr가 온다고 가정해야 한다.
    v1: 8단계 / v2: +archives·pdf·sqlite·video_integrity·audio_fp

사용:
    python scripts/case_survey.py case/ -o survey.json
    python scripts/case_survey.py case/ --keywords "계좌,송금" --stt -o survey.json
    python scripts/case_survey.py case/ --markdown survey.md

알려진 한계:
- 각 단계의 한계는 개별 스크립트와 docs/GAPS.md를 따른다.
- 이 리포트는 '표면 조사'다 — 카빙·MFT·메모리 분석은 BYO 도구 영역.
"""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from processing_receipt import TOOL_VERSION, build_receipt, utc_now_iso


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_step(name: str, fn) -> dict:
    """각 단계를 감싸 예외를 '실패' 기록으로 바꾼다."""
    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            result = fn()
        return {"status": "ok", "result": result}
    except SystemExit as e:
        return {"status": "failed", "exit": e.code,
                "stderr": buf_err.getvalue()[-500:]}
    except Exception as e:  # noqa: BLE001 — 단계 실패가 전체를 멈추지 않게
        return {"status": "failed", "error": f"{type(e).__name__}: {e}"}


def survey(root: Path, keywords: list[str], run_stt: bool, case_id=None, evidence_id=None) -> dict:
    started = utc_now_iso()
    root = root.resolve(strict=True)
    report: dict = {
        "survey_version": 2,
        "generated_at": datetime.now(KST).isoformat(),
        "root": str(root.resolve()),
        "steps": {},
    }

    def step_manifest():
        mod = _load("evidence_manifest")
        m = mod.build_manifest(root)
        return m
    report["steps"]["manifest"] = _run_step("manifest", step_manifest)

    # 단계별 rglob 반복을 피하기 위해 파일 목록을 한 번만 열거한다.
    all_files = sorted(p for p in root.rglob("*") if p.is_file())

    def by_ext(exts):
        return [p for p in all_files if p.suffix.lower() in exts]

    def step_pii():
        mod = _load("pii_mask")
        files = by_ext(mod.TEXT_EXTS)
        findings = [mod.process_file(f, mask=False, out_path=None, in_place=False)
                    for f in sorted(files)]
        total = sum(r.get("pii_count", 0) for r in findings)
        return {"files_scanned": len(files), "total_pii": total,
                "hits": [r for r in findings if r.get("pii_count")]}
    report["steps"]["pii"] = _run_step("pii", step_pii)

    if keywords:
        def step_keywords():
            mod = _load("keyword_report")
            searched, results, skipped = [], [], []
            for f in by_ext(mod.TEXT_EXTS):
                hits, read_error = mod.search_file_result(f, keywords, context=0)
                if read_error is not None:
                    skipped.append({"file": str(f), "error": read_error})
                    continue
                searched.append(str(f))
                if hits:
                    results.append({"file": str(f), "sha256": mod.sha256_file(f),
                                    "hit_count": len(hits), "hits": hits})
            return {"keywords": keywords, "files_searched": len(searched),
                    "total_hits": sum(r["hit_count"] for r in results),
                    "status": "partial" if skipped else "complete",
                    "skipped": skipped, "results": results}
        report["steps"]["keywords"] = _run_step("keywords", step_keywords)

    def step_audio():
        mod = _load("audio_survey")
        files = by_ext(mod.AUDIO_EXTS)
        return {"audio_files": len(files),
                "surveys": [mod.survey(f, mod.DEFAULT_THRESHOLD) for f in files]}
    report["steps"]["audio"] = _run_step("audio", step_audio)

    def step_exif():
        mod = _load("exif_audit")
        Image = mod._require_pillow()
        if Image is None:
            raise RuntimeError("Pillow 없음 — exif_audit 생략")
        files = by_ext(mod.IMG_EXTS)
        return {"image_files": len(files),
                "records": [mod.audit_image(f, Image) for f in files]}
    report["steps"]["exif"] = _run_step("exif", step_exif)

    def step_images():
        mod = _load("image_similarity")
        Image = mod._require_pillow()
        if Image is None:
            raise RuntimeError("Pillow 없음 — image_similarity 생략")
        records = mod.scan_dir(root, Image)
        return {"image_files": len(records),
                "similar_pairs": mod.find_pairs(records, 10)}
    report["steps"]["similar_images"] = _run_step("similar_images", step_images)

    def step_signatures():
        mod = _load("signature_check")
        records = [mod.audit_file(f) for f in all_files]
        return {"total": len(records),
                "mismatches": [r for r in records if r["status"] == "MISMATCH"],
                "match": sum(1 for r in records if r["status"] == "MATCH")}
    report["steps"]["signatures"] = _run_step("signatures", step_signatures)

    def step_dedup():
        mod = _load("dedup_files")
        files = [p for p in all_files if "__pycache__" not in p.parts]
        return {"exact_groups": mod.exact_dups(files),
                "similar_groups": mod.similar_image_groups(root)}
    report["steps"]["dedup"] = _run_step("dedup", step_dedup)

    def step_archives():
        mod = _load("archive_survey")
        records = mod.scan(root)
        flagged = [m for r in records for m in r.get("members", []) if m["flags"]]
        return {"archives": len(records), "flagged_members": len(flagged),
                "records": records}
    report["steps"]["archives"] = _run_step("archives", step_archives)

    def step_pdf():
        mod = _load("pdf_audit")
        records = mod.scan(root)
        return {"pdf_files": len(records),
                "flagged": sum(1 for r in records
                               if r.get("suspicious") or r.get("encrypted")),
                "records": records}
    report["steps"]["pdf"] = _run_step("pdf", step_pdf)

    def step_sqlite():
        mod = _load("sqlite_survey")
        records = mod.scan(root)
        return {"db_files": len(records),
                "broken": sum(1 for r in records
                              if r.get("is_sqlite") and not r.get("integrity_ok")),
                "records": records}
    report["steps"]["sqlite"] = _run_step("sqlite", step_sqlite)

    def step_videos():
        mod = _load("video_fingerprint")
        if not mod._require_ffmpeg():
            raise RuntimeError("ffmpeg 없음 — video_fingerprint 생략")
        files = by_ext(mod.VIDEO_EXTS)
        fps = []
        for f in sorted(files):
            try:
                fp = mod.fingerprint(f)
                fp["frame_hashes"] = [format(h, "016x") for h in fp["frame_hashes"]]
                fps.append(fp)
            except RuntimeError as e:
                fps.append({"file": str(f), "error": str(e)})
        return {"video_files": len(files), "fingerprints": fps}
    report["steps"]["videos"] = _run_step("videos", step_videos)

    def step_vintegrity():
        mod = _load("video_integrity")
        if not mod._require_ffmpeg():
            raise RuntimeError("ffmpeg 없음 — video_integrity 생략")
        files = by_ext(mod.VIDEO_EXTS)
        return {"video_files": len(files),
                "records": [mod.audit_video(f, run_decode=True)
                            for f in files]}
    report["steps"]["video_integrity"] = _run_step("video_integrity", step_vintegrity)

    def step_audio_fp():
        mod = _load("audio_fingerprint")
        if not mod._require_fpcalc():
            raise RuntimeError("fpcalc(chromaprint) 없음 — 오디오 지문 생략")
        files = by_ext(mod.AUDIO_EXTS)
        records = []
        for f in files:
            try:
                records.append(mod.fingerprint(f))
            except RuntimeError as e:
                records.append({"file": str(f), "error": str(e)})
        ok = [r for r in records if "fingerprint" in r]
        return {"audio_files": len(records),
                "similar_pairs": mod.find_pairs(ok)}
    report["steps"]["audio_fp"] = _run_step("audio_fp", step_audio_fp)

    if run_stt:
        def step_stt():
            mod = _load("local_stt")
            engine = mod.detect_engine()
            if engine is None:
                raise RuntimeError("로컬 STT 엔진 없음 — 전사 생략")
            files = by_ext(mod.AUDIO_EXTS)
            out = []
            for f in files:
                try:
                    r = mod.transcribe_file(f, engine, "ko", verbatim=False, model_size="turbo")
                    hits = mod.keyword_hits(r["segments"], keywords) if keywords else []
                    out.append({"file": str(f), "engine": r["engine"],
                                "segment_count": len(r["segments"]),
                                "keyword_hits": hits})
                except Exception as e:  # noqa: BLE001
                    out.append({"file": str(f), "error": str(e)[:300]})
            return {"engine": engine, "files": out}
        report["steps"]["stt"] = _run_step("stt", step_stt)

    def incomplete(value):
        if isinstance(value, dict):
            return bool(value.get("error")) or value.get("status") in (
                "failed", "partial", "DECODE_FAILED", "UNREADABLE") or any(incomplete(v) for v in value.values())
        if isinstance(value, list):
            return any(incomplete(v) for v in value)
        return False

    warnings = [f"Incomplete stage: {name}" for name, stage in report["steps"].items()
                if incomplete(stage)]
    report["processing_receipt"] = build_receipt(
        evidence_id or str(root), "case_survey", TOOL_VERSION, root,
        source_base=root, started_at=started, case_id=case_id,
        status="partial" if warnings else "complete", exit_code=None,
        warnings=warnings, parameters={"keywords": keywords, "run_stt": run_stt},
        limitations=["Directory source has no single-file SHA-256; use manifest entries",
                     "Stages are independent reads, not an atomic acquisition snapshot",
                     "Embedded receipt does not hash its enclosing JSON"],
    )
    return report


def to_markdown(report: dict) -> str:
    lines = [f"# 증거 선조사 리포트 — {report['root']}",
             f"생성: {report['generated_at']}", ""]
    names = {
        "manifest": "파일 매니페스트", "pii": "개인정보 탐지",
        "keywords": "키워드 검색", "audio": "오디오 발화 구간",
        "exif": "이미지 EXIF", "similar_images": "유사 이미지",
        "signatures": "시그니처 위장 감사", "dedup": "중복 파일",
        "archives": "아카이브 내부", "pdf": "PDF 감사",
        "sqlite": "SQLite DB 조사", "videos": "영상 지문",
        "video_integrity": "영상 무결성", "audio_fp": "오디오 지문",
        "stt": "로컬 STT",
    }
    for key, step in report["steps"].items():
        title = names.get(key, key)
        if step["status"] != "ok":
            lines.append(f"## {title}: 실패 — {step.get('error') or step.get('stderr', '')[:120]}")
            continue
        r = step["result"]
        if key == "manifest":
            lines.append(f"## {title}: {r['file_count']}개 파일")
        elif key == "pii":
            lines.append(f"## {title}: {r['total_pii']}건 탐지 ({r['files_scanned']}개 파일)")
            for h in r["hits"]:
                lines.append(f"- {h['file']}: {h['pii_count']}건")
        elif key == "keywords":
            lines.append(f"## {title}: {r['total_hits']}히트 ({r['files_searched']}개 파일 검색)")
            for res in r["results"]:
                lines.append(f"- {res['file']}: {res['hit_count']}히트")
        elif key == "audio":
            for s in r["surveys"]:
                if s["status"] == "ok":
                    lines.append(f"## {title}: {s['file']} — 발화 {s['speech_ratio']*100:.0f}%")
        elif key == "exif":
            present = sum(1 for x in r["records"] if x.get("exif_present"))
            lines.append(f"## {title}: {r['image_files']}개 이미지, EXIF 있음 {present}")
        elif key == "similar_images":
            lines.append(f"## {title}: {r['image_files']}개 이미지, 유사 쌍 {len(r['similar_pairs'])}건")
        elif key == "signatures":
            lines.append(f"## {title}: {r['total']}개 파일, 위장 의심 {len(r['mismatches'])}건")
            for m in r["mismatches"]:
                lines.append(f"- {m['file']}: 확장자 {m['ext']} ≠ {m['detected']}")
        elif key == "dedup":
            lines.append(f"## {title}: 정확 중복 {len(r['exact_groups'])}그룹, "
                         f"유사 이미지 {len(r['similar_groups'])}그룹")
        elif key == "archives":
            lines.append(f"## {title}: {r['archives']}개 아카이브, "
                         f"플래그 멤버 {r['flagged_members']}개")
            for rec in r["records"]:
                for m in rec.get("members", []):
                    if m["flags"]:
                        lines.append(f"- {rec['file']}::{m['name']} — {', '.join(m['flags'])}")
        elif key == "pdf":
            lines.append(f"## {title}: {r['pdf_files']}개 PDF, 주의 필요 {r['flagged']}건")
            for rec in r["records"]:
                for n in rec.get("notes", []):
                    lines.append(f"- {rec['file']}: {n}")
        elif key == "sqlite":
            lines.append(f"## {title}: {r['db_files']}개 DB, 무결성 이상 {r['broken']}건")
            for rec in r["records"]:
                if rec.get("tables"):
                    lines.append(f"- {rec['file']}: 테이블 {len(rec['tables'])}개, "
                                 f"총 {rec.get('total_rows', 0)}행")
        elif key == "videos":
            lines.append(f"## {title}: {r['video_files']}개 영상 지문 생성")
        elif key == "video_integrity":
            bad = [x for x in r["records"] if x["status"] != "OK"]
            lines.append(f"## {title}: {r['video_files']}개 영상, 이상 {len(bad)}건")
            for x in bad:
                lines.append(f"- {x['file']}: {'; '.join(x.get('notes', [])) or x.get('error', '')}")
        elif key == "audio_fp":
            lines.append(f"## {title}: {r['audio_files']}개 오디오, "
                         f"유사 쌍 {len(r['similar_pairs'])}건")
            for p in r["similar_pairs"]:
                lines.append(f"- {p['a']} ↔ {p['b']} (유사도 {p['similarity']})")
        elif key == "stt":
            for f in r["files"]:
                if "error" in f:
                    lines.append(f"## {title}: {f['file']} 실패")
                else:
                    lines.append(f"## {title}: {f['file']} — {f['segment_count']}세그먼트, "
                                 f"키워드 히트 {len(f.get('keyword_hits', []))}건")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="증거 디렉터리 통합 선조사 (로컬 전용)")
    ap.add_argument("root", help="증거 디렉터리")
    ap.add_argument("--keywords", default=None, help="쉼표 구분 키워드")
    ap.add_argument("--stt", action="store_true", help="로컬 STT 전사까지 실행")
    ap.add_argument("-o", "--output", default=None, help="JSON 리포트 경로")
    ap.add_argument("--markdown", default=None, help="마크다운 리포트 경로")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"디렉터리를 찾을 수 없습니다: {root}", file=sys.stderr)
        return 2

    keywords = [k.strip() for k in args.keywords.split(",")] if args.keywords else []
    report = survey(root, keywords, args.stt)

    failed = [k for k, v in report["steps"].items() if v["status"] != "ok"]
    out = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
    if args.markdown:
        Path(args.markdown).write_text(to_markdown(report), encoding="utf-8")
    if not args.output and not args.markdown:
        print(out)

    print(f"선조사 완료 — 단계 {len(report['steps'])}개 중 실패 {len(failed)}개"
          + (f" ({', '.join(failed)})" if failed else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
