"""slop_guard.mjs: 보고서 파일의 AI 상투 표현을 쓰는 즉시 표시한다(사용자 결정 2026-11-04, 경고만)."""
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "slop_guard.mjs"

SLOPPY_KO = (
    "# 분석 보고서\n\n"
    "이번 사건은 단순한 실수가 아니라 계획된 행위로 보인다. 결론적으로 매우 중요한 증거가 확보되었다.\n"
    "증거는 수사관에 의해 수집되어졌다. 이 자료는 높은 신뢰성을 가지고 있다.\n"
    "지금이야말로 추가 조사를 해야 할 때입니다.\n"
)
SLOPPY_EN = (
    "# Draft report\n\nThis case delves into a rich tapestry of evidence. It's important to note that the log "
    "stands as a testament to careful work, and it plays a pivotal role. In conclusion, the realm is intricate.\n"
)


def hook(tmp_path: Path, name: str, body: str):
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    payload = json.dumps({"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(f)}}})
    return subprocess.run(["node", str(SCRIPT)], input=payload, text=True, encoding="utf-8", capture_output=True)


def scan(tmp_path: Path, body: str, name: str = "x.md") -> dict[str, Any]:
    f = tmp_path / name
    f.write_text(body, encoding="utf-8")
    proc = subprocess.run(["node", str(SCRIPT), "--file", str(f)], text=True, encoding="utf-8", capture_output=True)
    return json.loads(proc.stdout)


@pytest.mark.parametrize("name,body", [("보고서.md", SLOPPY_KO), ("draft_report.md", SLOPPY_EN)])
def test_report_with_slop_warns_without_blocking(tmp_path, name, body):
    proc = hook(tmp_path, name, body)
    assert proc.returncode == 0 and proc.stdout.strip() == "{}", proc
    assert "[SLOP GUARD] WARN" in proc.stderr, proc.stderr
    assert "humanize-korean" in proc.stderr  # 밀도가 높으면 구간 모드를 제안한다


def test_non_report_files_are_not_checked(tmp_path):
    proc = hook(tmp_path, "notes.md", SLOPPY_KO)
    assert proc.returncode == 0 and proc.stdout.strip() == "{}" and proc.stderr == "", proc


def test_quotes_code_tables_and_blockquotes_are_not_flagged(tmp_path):
    body = (
        "# 보고서\n\n"
        '피의자는 "결론적으로 매우 중요한 일이 아니라 장난이었다"라고 말했다.\n'
        "> 결론적으로 매우 중요한 자료에 의해 수집되어졌다\n"
        "| 날짜 | 인용 |\n|---|---|\n| 10-03 | 결론적으로 매우 중요하다 |\n"
        "```\nIn conclusion, delve into the tapestry\n```\n"
    )
    assert scan(tmp_path, body)["findings"] == []


def test_anti_tells_are_not_flagged(tmp_path):
    # 자체 측정에서 사람이 더 많이 쓴 표현(~를 통해, ~것이다, 괄호)은 슬롭으로 보지 않는다
    body = "# 보고서\n\n로그 분석을 통해 접속 시각을 확인했다. 이는 계획된 접속이었던 것이다(관리자 계정).\n"
    assert scan(tmp_path, body)["findings"] == []


def test_real_kakao_report_has_no_false_alarm(tmp_path):
    body = (
        "# 카카오톡 대화 보고서\n\n| 날짜 | 시각 | 발언자 | 인용 |\n| --- | --- | --- | --- |\n"
        "| 2026-10-03 | 12:40 | 이지은 | 300만원은 어렵고 200만원만 입금할게 |\n\n- 카카오톡 대화: 6건\n- 김민수: 4건\n"
    )
    res = scan(tmp_path, body)
    assert res["weight"] == 0 and res["hygiene"] == []


def hygiene_ids(tmp_path: Path, body: str, name: str = "x.md") -> list[tuple[str, int]]:
    return [(h["id"], h["line"]) for h in scan(tmp_path, body, name)["hygiene"]]


# 아래는 사용자가 후임에게 보낸 포렌식 보고서 수정 지시서(2026-11-04)의 Before 예문이다.
@pytest.mark.parametrize(
    "line",
    [
        "시스템 디스크(SSD)는2026.10.27. 이미징했다.",
        "저장소(Repository)는Git으로 관리된다.",
        "원격 주소(origin)로지정된 저장소다.",
        "작업 폴더(E: 볼륨)에는13개의 저장소가 있다.",
        "계정(gudc0831)에연결하여 푸시했다.",
        "이미징 개시(10.27. 16:59:12)까지운영체제가 켜져 있었다.",
        "내부 전달 폴더(발신본)의반영 내역이다.",
    ],
)
def test_missing_space_after_paren_is_flagged(tmp_path, line):
    assert ("paren-spacing", 1) in hygiene_ids(tmp_path, line)


@pytest.mark.parametrize(
    "line",
    ["(주)에스원과 계약했다.", "경로(E:)에서는 없다.", "원본(SSD)으로부터 복사했다.", "파일(A)와의 차이다.", "폴더(HDD)로 옮겼다."],
)
def test_correct_paren_spacing_is_not_flagged(tmp_path, line):
    assert hygiene_ids(tmp_path, line) == []


def test_report_layout_problems_from_instructions_are_flagged(tmp_path):
    body = "\n".join(
        [
            "# 보고서",
            "파일 22,071,970,979 Bytes / 22.07GB를 복사했다.",
            "근거는 #436885(근거 65행)에 있다.",
            "이미지('미리보기.jpg', '메뉴순서.jpg', 'pdf-contact-sheet.png')가 삭제되었다.",
            "업무 자료를 외장하드로 옮긴 정황입니다.",
            "| 반출 | " + "가" * 320 + " |",
            "| 정리 | 짧은 셀<br>" + "나" * 200 + "<br>" + "다" * 200 + " |",
            "수령 상태: 입력하세요",
        ]
    )
    assert hygiene_ids(tmp_path, body) == [
        ("bytes-raw", 2),
        ("inline-evidence-ref", 3),
        ("filename-list", 4),
        ("overclaim", 5),
        ("brick-cell", 6),
        ("placeholder", 8),
    ]


def test_summary_retold_in_next_sections_is_flagged(tmp_path):
    body = (
        "[요지]\n개인 저장소로 전송된 후 제외된 파일은 754개이며 이 중 122개는 내용까지 삭제되었습니다.\n\n"
        "[해설]\n754개 중 632개는 동일한 내용이 다른 경로에 남아 있어 경로가 변경된 것이고 122개(workspace-skep 87개)는 남아 있지 않습니다.\n\n"
        "[상세 분석]\n저장소에서 빠진 파일도 754개 있습니다. 632개는 같은 내용이 다른 경로에 남아 있어 경로를 옮긴 것이고 122개는 "
        "내용까지 없어졌습니다. 없어진 파일은 workspace-skep 87개입니다.\n"
    )
    assert ("summary-echo", 7) in hygiene_ids(tmp_path, body)


def test_repeated_notice_sentence_is_flagged_once(tmp_path):
    note = "※ 근거 칸의 #번호는 AXIOM 사건 데이터베이스의 항목 번호이며 엑셀 시트에서 찾을 수 있다."
    body = f"# 1장\n{note}\n\n# 2장\n{note}\n\n# 3장\n{note}\n"
    assert hygiene_ids(tmp_path, body) == [("repeat-sentence", 5)]


def test_json_and_html_reports_are_checked(tmp_path):
    doc = {"blocks": [{"id": "b7", "ph": "수령 당시 기기 상태 입력..."}, {"sign": {"writer": "임기택<br>"}}]}
    assert hygiene_ids(tmp_path, json.dumps(doc, ensure_ascii=False), "보고서.json") == [("placeholder", 0), ("stray-br", 0)]
    html = "<p>디스크(SSD)는2026.10.27. 이미징했다.</p><table><tr><td>반출</td><td>" + "가" * 320 + "</td></tr></table>"
    assert [i for i, _ in hygiene_ids(tmp_path, html, "report.html")] == ["paren-spacing", "brick-cell"]


def test_layout_problems_alone_still_warn_with_fix(tmp_path):
    proc = hook(tmp_path, "본권_보고서.md", "# 보고서\n\n시스템 디스크(SSD)는2026.10.27. 이미징했다.\n")
    assert proc.returncode == 0 and proc.stdout.strip() == "{}", proc
    assert "[SLOP GUARD] WARN" in proc.stderr and "괄호 뒤 띄어쓰기 누락 1건" in proc.stderr, proc.stderr
