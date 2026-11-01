"""test_guards_sync.py — lazyothers 동기화 가드(markdown_structure_guard, stop_claim_guard, legal_factuality_guard) 검증."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = "node"


def run_node_script(script_name, args=(), stdin_payload=None, env=None, cwd=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(
        [NODE, str(ROOT / "scripts" / script_name), *args],
        input=stdin_payload,
        text=True, encoding="utf-8", errors="replace",
        capture_output=True,
        env=e,
        cwd=str(cwd or ROOT),
    )


def test_markdown_structure_guard_blocks_unclosed_evidence(tmp_path):
    f = tmp_path / "broken_evidence.md"
    f.write_text("# 문서\n<evidence>열기만 함\n", encoding="utf-8")
    proc = run_node_script("markdown_structure_guard.mjs", ["--check", str(f)])
    assert proc.returncode == 1
    assert "unclosed_evidence_tag" in proc.stderr


def test_markdown_structure_guard_blocks_empty_evidence(tmp_path):
    f = tmp_path / "empty_evidence.md"
    f.write_text("# 문서\n<evidence></evidence>\n", encoding="utf-8")
    proc = run_node_script("markdown_structure_guard.mjs", ["--check", str(f)])
    assert proc.returncode == 1
    assert "empty_evidence_block" in proc.stderr


def test_markdown_structure_guard_blocks_broken_citation(tmp_path):
    f = tmp_path / "broken_cite.md"
    f.write_text("# 문서\n본문【F:source.pdf†L50】인용\n", encoding="utf-8")
    proc = run_node_script("markdown_structure_guard.mjs", ["--check", str(f)])
    assert proc.returncode == 1
    assert "broken_citation_token" in proc.stderr


def test_stop_claim_guard_blocks_unsupported_claim():
    payload = json.dumps({
        "hook_event_name": "Stop",
        "last_assistant_message": "법률 문서 작성을 완료했습니다.",
    })
    proc = run_node_script("stop_claim_guard.mjs", stdin_payload=payload, env={"LAZYARGON_STOP_GUARD": "enforce"})
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data.get("decision") == "continue"


@pytest.mark.parametrize("message,checked", [
    ("설치된 Dissect 버전에는 브라우저 기능이 없습니다.", True),
    ("결과 수치는 두 번 모두 맞았습니다.", True),
    ("이 파서는 macOS·Linux에서도 동작합니다.", True),
    ("Safari 기록은 권한이 없어 확인하지 못했습니다.", False),
    ("도구 없이는 README 파일의 존재 여부를 확인할 수 없습니다.", False),
    ("Windows에서 직접 실행해 확인하지는 못했으나, 코드는 Windows에서 문제없이 동작합니다.", True),
    ("Linux에서는 아직 실행하지 않아 미확인입니다.", False),
    ("문제 없습니다. 테스트 790개가 통과했습니다.", False),
])
def test_stop_claim_guard_self_check_on_risky_claims(tmp_path, message, checked):
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "last_assistant_message": message}, ensure_ascii=False)
    proc = run_node_script("stop_claim_guard.mjs", stdin_payload=payload)
    out = json.loads(proc.stdout)
    assert (out.get("decision") == "continue" and "SELF-CHECK" in out.get("reason", "")) is checked, out
    again = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "stop_hook_active": True, "last_assistant_message": message}, ensure_ascii=False)
    assert json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=again).stdout) == {}
    off = run_node_script("stop_claim_guard.mjs", stdin_payload=payload, env={"LAZYARGON_SELF_CHECK": "off"})
    assert "SELF-CHECK" not in off.stdout


def _turn_transcript(tmp_path, outputs, calls=1):
    steps: list[dict[str, object]] = [{"type": "USER_INPUT", "content": "질문"}]
    for o in outputs:
        steps.append({"type": "PLANNER_RESPONSE", "content": "", "tool_calls": [{"name": "run_command", "args": {}}] * calls})
        steps.append({"type": "GENERIC", "content": o})
    tp = tmp_path / "transcript_full.jsonl"
    tp.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps), encoding="utf-8")
    return str(tp)


@pytest.mark.parametrize("outputs,message,checked", [
    (["Command output:\n42"], "로그 줄은 42건입니다.", False),
    (["Command output:\n42"], "로그인 기록 57건이 확인되었습니다.", True),
    (["ModuleNotFoundError: No module named 'x.browsers'"], "브라우저 기능이 없습니다.", True),
    (["report.py:42 에서 표를 만들지 않음", "ok"], "표가 출력되지 않습니다.", False),
])
def test_stop_claim_guard_uses_turn_evidence(tmp_path, outputs, message, checked):
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "last_assistant_message": message,
                          "transcriptPath": _turn_transcript(tmp_path, outputs)}, ensure_ascii=False)
    out = json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=payload).stdout)
    assert ("SELF-CHECK" in out.get("reason", "")) is checked, out


def test_stop_claim_guard_asks_once_per_turn_and_skips_scoped_absence(tmp_path):
    tp = _turn_transcript(tmp_path, ["ls: /p/x.py: No such file or directory"])
    base = {"hook_event_name": "Stop", "conversationId": "c9", "cwd": str(tmp_path), "transcriptPath": tp}
    scoped = json.dumps({**base, "last_assistant_message": "/p/x.py: 파일 없음"}, ensure_ascii=False)
    assert json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=scoped).stdout) == {}
    broad = json.dumps({**base, "last_assistant_message": "브라우저 기능이 없습니다."}, ensure_ascii=False)
    first = json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=broad).stdout)
    assert "SELF-CHECK" in first.get("reason", "")
    assert json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=broad).stdout) == {}
    new_kind = json.dumps({**base, "executionNum": 1, "last_assistant_message": "Linux에서도 동작합니다."}, ensure_ascii=False)
    assert "SELF-CHECK" in json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=new_kind).stdout).get("reason", "")
    capped = json.dumps({**base, "executionNum": 2, "last_assistant_message": "전부 맞았습니다."}, ensure_ascii=False)
    assert json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=capped).stdout) == {}


@pytest.mark.parametrize("outputs,message,checked", [
    ([], "현재 Python의 최신 안정 버전은 Python 3.13입니다.", True),
    ([], "학습 시점 기준 최신은 3.13이지만 지금은 확인하지 못했습니다.", False),
    (["Python 3.14.0 released"], "최신 안정 버전은 3.14입니다.", False),
])
def test_stop_claim_guard_flags_fresh_facts_without_tools(tmp_path, outputs, message, checked):
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "last_assistant_message": message,
                          "transcriptPath": _turn_transcript(tmp_path, outputs)}, ensure_ascii=False)
    out = json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=payload).stdout)
    assert ("SELF-CHECK" in out.get("reason", "")) is checked, out


@pytest.mark.skipif(sys.platform != "darwin", reason="호스트 OS 가 macOS 일 때의 다른 환경 판정")
@pytest.mark.parametrize("question,message,checked", [
    ("tool.py 를 Windows에서 실행하면 무엇이 출력되나?", "`\\` (백슬래시)가 출력됩니다.", True),
    ("tool.py 를 Windows에서 실행하면 무엇이 출력되나?", "예상 출력은 \\ 이며 Windows에서 실행하지 못했습니다.", False),
    ("tool.py 를 실행하면 무엇이 출력되나?", "/ 가 출력됩니다.", False),
])
def test_stop_claim_guard_flags_outcomes_on_unrun_os(tmp_path, question, message, checked):
    steps = [{"type": "USER_INPUT", "content": question},
             {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "view_file", "args": {}}]},
             {"type": "GENERIC", "content": "import os\nprint(os.sep)"}]
    tp = tmp_path / "transcript_full.jsonl"
    tp.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps), encoding="utf-8")
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "last_assistant_message": message,
                          "transcriptPath": str(tp)}, ensure_ascii=False)
    out = json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=payload).stdout)
    assert ("SELF-CHECK" in out.get("reason", "")) is checked, out


@pytest.mark.parametrize("message,checked", [
    ('점검: 근거 있음 — `ls /p/x.py` 실행 결과 "No such file or directory"', False),
    ('점검: 근거 있음 — `ls /p/x.py` 실행 결과 "x.py 크기 120 bytes"', True),
])
def test_stop_claim_guard_checks_cited_evidence_in_self_check_reply(tmp_path, message, checked):
    steps = [{"type": "USER_INPUT", "content": "q"},
             {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls /p/x.py"}}]},
             {"type": "GENERIC", "content": "ls: /p/x.py: No such file or directory"}]
    tp = tmp_path / "transcript_full.jsonl"
    tp.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps), encoding="utf-8")
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "executionNum": 1,
                          "last_assistant_message": message, "transcriptPath": str(tp)}, ensure_ascii=False)
    out = json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=payload).stdout)
    assert ("근거 인용 불일치" in out.get("reason", "")) is checked, out


@pytest.mark.parametrize("command,message,checked", [
    ("ls -1 /p/scripts/*.py | wc -l", ".py 파일 개수: 3개", False),
    ("wc -l /p/logs/auth.log", "로그인 기록은 3건입니다.", True),
])
def test_stop_claim_guard_wc_l_entries_vs_lines(tmp_path, command, message, checked):
    steps = [{"type": "USER_INPUT", "content": "q"},
             {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": command}}]},
             {"type": "GENERIC", "content": "Command output:\n       3"}]
    tp = tmp_path / "transcript_full.jsonl"
    tp.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps), encoding="utf-8")
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "last_assistant_message": message,
                          "transcriptPath": str(tp)}, ensure_ascii=False)
    out = json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=payload).stdout)
    assert ("SELF-CHECK" in out.get("reason", "")) is checked, out


@pytest.mark.parametrize("command,output,warned", [
    ("Test-Path C:\\temp\\registry_parser.py", "False", True),
    ("Test-Path C:\\temp\\tool.py", "True", False),
    ("Get-ChildItem C:\\temp\\reports", "Get-ChildItem : '\uacbd\ub85c\ub97c \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4' ... ItemNotFoundException", True),
    ("Get-Content C:\\temp\\a.txt", "hello", False),
])
def test_lookup_guard_powershell_lookups(tmp_path, command, output, warned):
    steps = [{"type": "USER_INPUT", "content": "q"},
             {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": command}}]},
             {"type": "GENERIC", "step_index": 2, "content": f"Command exited with code 0.\n\nCommand output:\n{output}\n"}]
    tp = tmp_path / "transcript_full.jsonl"
    tp.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps), encoding="utf-8")
    payload = json.dumps({"conversationId": "ps1", "toolCall": {"name": "run_command", "args": {"CommandLine": command}},
                          "stepIdx": 1, "cwd": str(tmp_path), "transcriptPath": str(tp)})
    proc = run_node_script("lookup_guard.mjs", stdin_payload=payload)
    assert ("[LOOKUP GUARD] WARN" in proc.stderr) is warned, proc.stderr


def _one_call_transcript(tmp_path, user, name, args, output):
    steps = [{"type": "USER_INPUT", "content": user},
             {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": name, "args": args}]},
             {"type": "GENERIC", "step_index": 2, "content": output}]
    tp = tmp_path / "transcript_full.jsonl"
    tp.write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in steps), encoding="utf-8")
    return str(tp)


@pytest.mark.parametrize("user,args,output,message,checked", [
    # Windows QA 2026-11-02: Test-Path 는 출력에 False 만 남기고 경로는 인자에만 있다
    ("q", {"CommandLine": "Test-Path \"C:\\temp\\lazyqa\\registry_parser.py\""}, "False",
     "C:\\temp\\lazyqa\\registry_parser.py 경로에 해당 파일이 없습니다.", False),
    ("q", {"CommandLine": "Test-Path \"C:\\temp\\lazyqa\\registry_parser.py\""}, "False",
     "엑셀 내보내기 기능이 없습니다.", True),
    # 호스트 환경을 말하는 문장은 다른 OS 결과 단정이 아니다(맥에서는 macOS 가 호스트)
    ("Linux 에서도 되나?", {"CommandLine": "python3 tool.py"}, "/", "macOS에서 실행하면 / 가 출력됩니다.", False),
    # read_file 머리글의 'lines' 는 줄 수 출력이 아니다
    ("q", {"AbsolutePath": "/p/a.txt"}, "File Path: /p/a.txt\nTotal Lines: 3\nShowing lines 1-3\n1: a\n2: b\n3: c",
     "파일은 3개 항목입니다.", False),
])
def test_stop_claim_guard_windows_qa_cases(tmp_path, user, args, output, message, checked):
    if "macOS" in message and sys.platform != "darwin":
        pytest.skip("호스트 OS 가 macOS 일 때의 판정")
    tp = _one_call_transcript(tmp_path, user, "run_command" if "CommandLine" in args else "read_file", args, output)
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path), "last_assistant_message": message,
                          "transcriptPath": tp}, ensure_ascii=False)
    out = json.loads(run_node_script("stop_claim_guard.mjs", stdin_payload=payload).stdout)
    assert ("SELF-CHECK" in out.get("reason", "")) is checked, out


def test_lookup_guard_read_file_not_found(tmp_path):
    tp = _one_call_transcript(tmp_path, "q", "read_file", {"AbsolutePath": "C:\\temp\\x.py"}, "Error: file does not exist: C:\\temp\\x.py")
    payload = json.dumps({"conversationId": "rf", "toolCall": {"name": "read_file", "args": {"AbsolutePath": "C:\\temp\\x.py"}},
                          "stepIdx": 1, "cwd": str(tmp_path), "transcriptPath": tp})
    assert "[LOOKUP GUARD] WARN" in run_node_script("lookup_guard.mjs", stdin_payload=payload).stderr


def test_lookup_guard_warns_on_failed_lookup(tmp_path):
    steps = [{"type": "USER_INPUT", "content": "q"},
             {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls /x/browsers"}}]},
             {"type": "GENERIC", "step_index": 2, "content": "ls: /x/browsers: No such file or directory"},
             {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls -la /x/scripts"}}]},
             {"type": "GENERIC", "step_index": 4, "content": "a.py b.py"}]
    tp = tmp_path / "transcript_full.jsonl"
    tp.write_text("\n".join(json.dumps(s) for s in steps), encoding="utf-8")
    payload = json.dumps({"conversationId": "c1", "toolCall": {"name": "run_command", "args": {"CommandLine": "ls -la /x/scripts"}},
                          "stepIdx": 3, "cwd": str(tmp_path), "transcriptPath": str(tp)})
    proc = run_node_script("lookup_guard.mjs", stdin_payload=payload)
    assert proc.stdout.strip() == "{}" and "[LOOKUP GUARD] WARN" in proc.stderr
    assert "ls /x/browsers" in proc.stderr and "/x/scripts" not in proc.stderr
    again = run_node_script("lookup_guard.mjs", stdin_payload=payload)
    assert "WARN" not in again.stderr


def test_stop_claim_guard_passes_strict_abstention():
    payload = json.dumps({
        "hook_event_name": "Stop",
        "last_assistant_message": "[INSUFFICIENT_DATA] 사실관계 추가 확인 필요.",
    })
    proc = run_node_script("stop_claim_guard.mjs", stdin_payload=payload)
    assert proc.returncode == 0
    assert proc.stdout.strip() == "{}"


def test_stop_claim_guard_blocks_phantom_files(tmp_path):
    payload = json.dumps({
        "hook_event_name": "Stop",
        "cwd": str(tmp_path),
        "last_assistant_message": "테스트 5 pass. 산출물: draft/phantom_sojang.md 생성을 완료했습니다.",
    })
    proc = run_node_script("stop_claim_guard.mjs", stdin_payload=payload, env={"LAZYARGON_STOP_GUARD": "enforce"})
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data.get("decision") == "continue"
    assert "Fact-Retracing" in data.get("reason", "")


def test_legal_factuality_guard_blocks_fake_statute(tmp_path):
    bad = tmp_path / "소장_초안.md"
    bad.write_text("# 소장\n원고는 민법 제1500조에 기하여 청구한다.", encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": str(bad)}})
    proc = run_node_script("legal_factuality_guard.mjs", stdin_payload=payload)
    assert proc.returncode == 1
    assert "LEGAL FACTUALITY GUARD" in proc.stderr
    assert "민법" in proc.stderr


def test_legal_factuality_guard_passes_clean_legal_doc(tmp_path):
    clean = tmp_path / "소장_초안.md"
    clean.write_text("# 소장\n원고는 민법 제750조에 기하여 청구한다. 변호사 검토 필수.", encoding="utf-8")
    payload = json.dumps({"tool_input": {"file_path": str(clean)}})
    proc = run_node_script("legal_factuality_guard.mjs", stdin_payload=payload)
    assert proc.returncode == 0


def test_post_tool_feedback_queues_failure_and_injects_once(tmp_path):
    env = {"LAZYARGON_FEEDBACK_DIR": str(tmp_path)}
    payload = json.dumps({"conversationId": "conv-fb"})
    failing = ["wrap", NODE, "-e", "process.stderr.write('GUARD BROKE'); process.exit(1)"]
    proc = run_node_script("post_tool_feedback.mjs", failing, stdin_payload=payload, env=env)
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {}
    assert "GUARD BROKE" in (tmp_path / "conv-fb.jsonl").read_text(encoding="utf-8")

    first = run_node_script("post_tool_feedback.mjs", ["inject"], stdin_payload=payload, env=env)
    assert "GUARD BROKE" in json.loads(first.stdout)["injectSteps"][0]["ephemeralMessage"]
    assert not (tmp_path / "conv-fb.jsonl").exists()
    second = run_node_script("post_tool_feedback.mjs", ["inject"], stdin_payload=payload, env=env)
    assert json.loads(second.stdout) == {}


def test_post_tool_feedback_relays_passing_guard_warning(tmp_path):
    env = {"LAZYARGON_FEEDBACK_DIR": str(tmp_path)}
    payload = json.dumps({"conversationId": "conv-warn"})
    warning = ["wrap", NODE, "-e", "process.stderr.write('[HALLUCINATION GUARD] WARN — r.md: 미확인 인용'); process.stdout.write('{}')"]
    run_node_script("post_tool_feedback.mjs", warning, stdin_payload=payload, env=env)
    quiet = ["wrap", NODE, "-e", "process.stderr.write('[HALLUCINATION GUARD] timeline 미발견'); process.stdout.write('{}')"]
    run_node_script("post_tool_feedback.mjs", quiet, stdin_payload=json.dumps({"conversationId": "conv-quiet"}), env=env)
    assert not (tmp_path / "conv-quiet.jsonl").exists()
    msg = json.loads(run_node_script("post_tool_feedback.mjs", ["inject"], stdin_payload=payload, env=env).stdout)
    text = msg["injectSteps"][0]["ephemeralMessage"]
    assert "경고를 남겼다" in text and "미확인 인용" in text and "실패를 보고했다" not in text


def test_hallucination_guard_checks_any_text_file_next_to_evidence(tmp_path):
    (tmp_path / "evidence").mkdir()
    (tmp_path / "evidence" / "chat.txt").write_text("2026년 3월 12일 오후 2:09, 김철수 : 내일 꼭 줄게\n", encoding="utf-8")
    note = tmp_path / "김철수_정리.md"
    note.write_text('# 정리\n김철수는 "돈을 이미 보냈다"라고 했다.\n', encoding="utf-8")
    payload = json.dumps({"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(note)}}})
    proc = run_node_script("hallucination_guard.mjs", stdin_payload=payload)
    assert proc.returncode == 1
    assert "원본에 없는 인용" in proc.stderr


def test_hallucination_guard_skips_files_inside_source_folder(tmp_path):
    src = tmp_path / "evidence"
    src.mkdir()
    raw = src / "unified_log.txt"
    raw.write_text('2026-10-31 09:00:00 | loginwindow "사건 보고서 작성용 원본"\n', encoding="utf-8")
    payload = json.dumps({"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(raw), "CodeContent": "보고서"}}}, ensure_ascii=False)
    proc = run_node_script("hallucination_guard.mjs", stdin_payload=payload)
    assert proc.returncode == 0, proc.stderr
    assert "FAIL" not in proc.stderr


def test_hooks_json_contains_legal_guard():
    hooks_data = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
    ptu = hooks_data.get("hooks", {}).get("PostToolUse", [])
    commands = [h["command"] for entry in ptu for h in entry.get("hooks", [])]
    assert any("legal_factuality_guard.mjs" in c for c in commands)


def test_hooks_matchers_cover_write_file_and_shell():
    hooks_data = json.loads((ROOT / "hooks.json").read_text(encoding="utf-8"))
    ptu = hooks_data["hooks"]["PostToolUse"]
    write_m = ptu[0]["matcher"]
    shell_m = ptu[1]["matcher"] if len(ptu) > 1 else ptu[0]["matcher"]
    for token in ("write_file", "WriteToFile", "WriteFile", "MultiEdit", "SearchReplace"):
        assert token in write_m
    for token in ("Bash", "bash", "Shell", "shell", "execute_command"):
        assert token in shell_m
    post_cmds = [h["command"] for grp in ptu for h in grp["hooks"]]
    assert len(post_cmds) == len(set(post_cmds))


def test_mcp_config_covers_bundled_servers(tmp_path):
    config = json.loads((ROOT / "mcp_config.json").read_text(encoding="utf-8"))
    registered = set(config.get("mcpServers", {}))
    bundled = {entry.name for entry in (ROOT / "mcp").iterdir() if entry.is_dir()}
    for tool in bundled:
        assert tool in registered

