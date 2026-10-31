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

