#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Phase 2 D:\ 실무 데이터 적대적 리플레이 회귀 테스트."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, rel: str):
    p = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_local_stt_win_symlink_fallback_copies_and_restores(tmp_path):
    local_stt = _load("local_stt", "scripts/local_stt.py")
    src = tmp_path / "blob"
    src.write_text("weights", encoding="utf-8")
    dst = tmp_path / "sub" / "model.bin"

    def fake_symlink(s, d, *a, **kw):
        err = OSError("privilege not held")
        err.winerror = 1314
        raise err

    orig = os.symlink
    with mock.patch.object(os, "name", "nt"), mock.patch.object(os, "symlink", fake_symlink):
        with local_stt._win_symlink_fallback():
            os.symlink(str(src), str(dst))
        assert os.symlink is fake_symlink
    assert dst.read_text(encoding="utf-8") == "weights"
    assert os.symlink is orig


def test_local_ocr_keyword_hits_and_fail_closed(tmp_path):
    local_ocr = _load("local_ocr", "scripts/local_ocr.py")
    blocks = [
        {"text": "2025년 1월 매입 합계 150,000,000원", "confidence": 0.98},
        {"text": "기타 비고 사항", "confidence": 0.91},
    ]
    hits = local_ocr.keyword_hits(blocks, ["매입", "합계"])
    assert len(hits) == 2
    assert local_ocr.main([str(tmp_path / "missing.png"), "--engine", "invalid-engine"]) == 3


def test_deepfake_unparsed_does_not_claim_normal_spectrum():
    df = _load("analyze_deepfake_evidence", "scripts/analyze_deepfake_evidence.py")
    data = {
        "meta": {"analyzed_at": "2026-10-14T00:00:00Z", "target_file": "fake.png", "analyzer_version": "1.0"},
        "integrity_hashes": {"size_bytes": 120, "sha256": "a" * 64, "sha1": "b" * 40, "md5": "c" * 32},
        "c2pa_provenance": {"c2pa_detected": False, "manifest_type": None, "details": []},
        "spectral_analysis": {
            "analyzed": False,
            "verdict_indicator": "INCONCLUSIVE (Pillow/NumPy 미설치 또는 이미지 손상)",
            "checkerboard_spikes_detected": False,
            "notes": ["이미지 디코딩 실패"],
        },
    }
    md = df.format_markdown_report(data)
    assert "미측정 (분석 미수행/실패)" in md
    assert "정상 (자연 사진 스펙트럼 곡선)" not in md


def test_signature_check_detects_html_disguised_as_png(tmp_path):
    sig = _load("signature_check", "scripts/signature_check.py")
    fake_png = tmp_path / "emoticon_text_144015.png"
    fake_png.write_text("<!doctype html>\n<html><body>Error 404</body></html>", encoding="utf-8")
    res = sig.audit_file(fake_png)
    assert res["status"] == "MISMATCH"
    assert res["detected"] == "HTML"


def test_dlp_log_table_xlsx_and_column_dedup(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    dlp = _load("dlp_log_table", "scripts/dlp_log_table.py")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["탐지 일시 (Event Time)", "탐지 정책 (Policy)", "유출 채널 (Channel)", "파일명"])
    ws.append(["2026-04-01 09:00:00", "소스코드 반출 차단", "USB 이동식 저장매체", "secret.zip"])
    xlsx_path = tmp_path / "dlp.xlsx"
    wb.save(xlsx_path)

    headers, rows = dlp.load_rows(xlsx_path)
    t_col = dlp.pick_col(headers, None, ["time", "date", "시각", "일시", "timestamp"])
    e_col = dlp.pick_col(headers, None, ["event", "action", "행위", "내용", "정책", "policy"], exclude={t_col})
    s_col = dlp.pick_col(headers, None, ["src", "source", "출처", "채널", "channel"], exclude={t_col, e_col})
    assert t_col == "탐지 일시 (Event Time)"
    assert e_col == "탐지 정책 (Policy)"
    assert s_col == "유출 채널 (Channel)"
    assert len(rows) == 1


def test_trace_financial_flow_t_account_and_spaced_headers(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    tff = _load("trace_financial_flow", "scripts/trace_financial_flow.py")
    wb = openpyxl.Workbook()
    ws0 = wb.active
    ws0.title = "계좌"
    ws0.append(["은행", "계좌번호", "성함"])
    ws0.append(["국민", "123-456", "홍길동"])

    ws1 = wb.create_sheet("10-4")
    ws1.append(["2 0 2 3 년  10 월 4 일  수요 일", None, None, None, None, None])
    ws1.append(["거 래 처", "입 금 액", "적 요", "거 래 처", "출 금 액", "적 요"])
    ws1.append(["모아리", 150000000, "이체", "대명", 50000000, "지급"])
    ws1.append(["합 계", 150000000, None, "합 계", 50000000, None])

    xlsx_path = tmp_path / "t_account.xlsx"
    wb.save(xlsx_path)

    cols, rows = tff.read_rows(str(xlsx_path))
    recs = tff.normalize(cols, rows)
    assert len(recs) == 2
    kinds = {r["counterparty"]: (r["kind"], r["amount"], r["date"]) for r in recs}
    assert kinds["모아리"] == ("입금", 150000000.0, "2023-10-04")
    assert kinds["대명"] == ("출금", -50000000.0, "2023-10-04")


def test_audit_timestamps_directory_mode(tmp_path, capsys):
    at = _load("audit_timestamps", "skills/forensic-audit/scripts/audit_timestamps.py")
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")
    (tmp_path / "b.txt").write_text("beta", encoding="utf-8")
    rc = at.main([str(tmp_path), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["file_count"] == 2
    assert len(out["files"]) == 2


def test_parse_kakao_directory_mode(tmp_path):
    pk = _load("parse_kakao", "skills/kakao-chat-extractor/scripts/parse_kakao.py")
    (tmp_path / "room1.txt").write_text(
        "--------------- 2025년 5월 28일 수요일 ---------------\n[홍길동] [오전 9:10] 첫 대화\n",
        encoding="utf-8",
    )
    (tmp_path / "room2.txt").write_text(
        "--------------- 2025년 5월 29일 목요일 ---------------\n[이순신] [오후 2:00] 둘째 대화\n",
        encoding="utf-8",
    )
    recs = pk.parse_kakao_file(str(tmp_path))
    assert len(recs) == 2
    assert {r["source_file"] for r in recs} == {"room1.txt", "room2.txt"}
