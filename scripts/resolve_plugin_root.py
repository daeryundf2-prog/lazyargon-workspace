#!/usr/bin/env python3
"""Resolve the lazyothers plugin root for Antigravity and Claude installs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REQUIRED_SCRIPT = Path("scripts") / "prepare_monolith_input.py"


def has_humanize_scripts(path: Path) -> bool:
	return (path / REQUIRED_SCRIPT).is_file()


def is_plugin_root(path: Path) -> bool:
	if not path.is_dir():
		return False
	return (path / "plugin.json").is_file() or (path / ".claude-plugin").is_dir()


def walk_from(start: Path) -> Path | None:
	current = start.resolve()
	seen: set[Path] = set()
	while current not in seen:
		seen.add(current)
		if is_plugin_root(current) and has_humanize_scripts(current):
			return current
		parent = current.parent
		if parent == current:
			return None
		current = parent
	return None


def resolve_plugin_root(start: str | None = None, env: dict[str, str] | None = None) -> Path:
	environ = env if env is not None else os.environ
	for key in ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"):
		raw = environ.get(key, "").strip()
		if not raw:
			continue
		candidate = Path(raw).expanduser()
		if is_plugin_root(candidate) and has_humanize_scripts(candidate):
			return candidate.resolve()
		raise FileNotFoundError(f"Invalid explicit plugin root: {key}")
	start_path = Path(start or environ.get("CLAUDE_SKILL_DIR") or environ.get("SKILL_DIR") or ".")
	found = walk_from(start_path.expanduser())
	if found is None:
		raise FileNotFoundError(
			"plugin root not found: set PLUGIN_ROOT or start from the humanize-korean skill directory"
		)
	return found


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Print the lazyothers plugin root")
	parser.add_argument("--start", help="Directory to walk upward from")
	args = parser.parse_args(argv)
	try:
		print(resolve_plugin_root(args.start))
	except FileNotFoundError as exc:
		print(str(exc), file=sys.stderr)
		return 2
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
