"""test_resolve_plugin_root.py — Antigravity PLUGIN_ROOT and plugin.json walk-up."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "resolve_plugin_root.py"


def load_resolver():
	spec = importlib.util.spec_from_file_location("resolve_plugin_root", MODULE_PATH)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def test_walk_from_skill_dir_finds_plugin_json():
	# given
	mod = load_resolver()
	skill_dir = ROOT / "skills" / "humanize-korean"
	# when
	found = mod.resolve_plugin_root(start=str(skill_dir), env={})
	# then
	assert found == ROOT
	assert (found / "scripts" / "prepare_monolith_input.py").is_file()


def test_plugin_root_env_wins_over_start(tmp_path):
	# given
	mod = load_resolver()
	env = {"PLUGIN_ROOT": str(ROOT)}
	# when
	found = mod.resolve_plugin_root(start=str(tmp_path), env=env)
	# then
	assert found == ROOT


def test_bogus_plugin_root_does_not_collapse_to_drive(tmp_path):
	# given
	mod = load_resolver()
	env = {"PLUGIN_ROOT": str(tmp_path)}
	# when / then
	with pytest.raises(FileNotFoundError):
		mod.resolve_plugin_root(start=str(tmp_path / "missing"), env=env)


def test_cli_prints_root():
	# given
	mod = load_resolver()
	# when
	code = mod.main(["--start", str(ROOT / "skills" / "humanize-korean")])
	# then
	assert code == 0
