import json
import shutil
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from e2e_evidence_pipeline import run_pipeline


def test_e2e_pipeline_full_workflow():
    tmp_dir = Path(tempfile.mkdtemp(prefix="test_e2e_pipeline_"))
    try:
        in_dir = tmp_dir / "inputs"
        in_dir.mkdir()
        out_dir = tmp_dir / "outputs"

        sample1 = in_dir / "kakao_chat.txt"
        sample1.write_text(
            "홍길동: 제 주민번호는 901212-1234568이고 전화번호는 010-9876-5432입니다.\n김변호사: 계좌번호 123-45-678901로 송금 바랍니다.",
            encoding="utf-8",
        )

        sample2 = in_dir / "bank_statement.csv"
        sample2.write_text(
            "일자,적요,출금,입금\n2026-05-01,법무법인 대륜 송무비용,5500000,0\n2026-05-02,거래대금 010-1234-5678,0,3000000\n",
            encoding="utf-8",
        )

        res = run_pipeline([sample1, sample2], out_dir, party="갑", start_no=1)
        assert res["status"] == "SUCCESS"
        assert res["count"] == 2

        # 산출물 확인
        summary_file = out_dir / "evidence_pipeline_summary.json"
        assert summary_file.exists()
        summary = json.loads(summary_file.read_text(encoding="utf-8"))
        assert summary["status"] == "PASS"
        assert summary["total_evidences"] == 2

        coc_file = out_dir / "증거목록_및_무결성증명서.md"
        assert coc_file.exists()
        coc_text = coc_file.read_text(encoding="utf-8")
        assert "갑 제1호증" in coc_text
        assert "갑 제2호증" in coc_text
        assert "법무법인(유한) 대륜" in coc_text

        # 마스킹 확인
        masked1 = out_dir / "masked_evidence" / "갑_제1호증_kakao_chat.txt"
        assert masked1.exists()
        masked1_text = masked1.read_text(encoding="utf-8")
        assert "901212-1234568" not in masked1_text
        assert "010-9876-5432" not in masked1_text
        assert "901212-1******" in masked1_text
        assert "010-9876-****" in masked1_text
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
