"""mcp_scaffold.py 회귀 테스트 — fastmcp 래퍼 생성기."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "mcp_scaffold.py"
TARGET = Path(__file__).resolve().parent.parent / "scripts" / "mask_korean_pii.py"


def run(args, cwd=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=cwd)


def test_scaffold_generates_parseable_server(tmp_path):
    r = run([str(TARGET), "--name", "pii-mask", "-o", str(tmp_path)])
    assert r.returncode == 0, r.stderr
    server = tmp_path / "pii-mask_server.py"
    assert server.exists()
    code = server.read_text(encoding="utf-8")
    compile(code, str(server), "exec")
    assert "FastMCP" in code
    assert "mask_korean_pii.py" in code


def test_emit_config_snippet(tmp_path):
    r = run(["scripts/mask_korean_pii.py", "--name", "pii-mask",
             "--emit-config", "-o", str(tmp_path)],
            cwd=SCRIPT.parent.parent)
    assert r.returncode == 0
    cfg = json.loads(r.stdout)
    assert cfg["pii-mask"]["command"] == "python3"
    assert cfg["pii-mask"]["args"][0].endswith("pii-mask_server.py")


def test_missing_script_exit_2(tmp_path):
    r = run(["nonexistent.py", "--name", "x", "-o", str(tmp_path)])
    assert r.returncode == 2


def test_bad_name_rejected():
    r = run(["scripts/mask_korean_pii.py", "--name", "!!bad",
             "--emit-config"], cwd=SCRIPT.parent.parent)
    assert r.returncode != 0
