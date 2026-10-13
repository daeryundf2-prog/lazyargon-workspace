"""플러그인 설치 스모크 — install.sh / install.ps1 의 플러그인 목록 정합성.

네트워크 없이 인스톨러 스크립트 자체를 검증한다:
- 셸/파워셸 인스톨러가 같은 플러그인 집합·같은 clone URL을 쓰는지
- --check 진단 목록과 clone 목록이 일치하는지
- config.json 활성화 목록이 clone 목록을 덮는지
- URL이 https GitHub clone 형식인지
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
INSTALL_PS1 = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")

EXPECTED_PLUGINS = {
    "lazyantigravity",
    "lazyforensic",
    "lazyothers",
    "lazydiagram",
}


def _sh_plugin_map():
    m = re.search(r'PLUGINS="\n(.*?)\n"', INSTALL_SH, re.S)
    assert m, "install.sh PLUGINS block not found"
    pairs = {}
    for line in m.group(1).splitlines():
        name, url = line.split()
        pairs[name] = url
    return pairs


def _ps1_repo_map():
    m = re.search(r"\$repos = @\{(.*?)\}", INSTALL_PS1, re.S)
    assert m, "install.ps1 $repos map not found"
    pairs = {}
    for name, url in re.findall(r'"([a-z0-9_-]+)"\s*=\s*"([^"]+)"', m.group(1)):
        pairs[name] = url
    return pairs


def test_shell_and_powershell_clone_lists_agree():
    assert _sh_plugin_map() == _ps1_repo_map()


def test_expected_plugin_set():
    assert set(_sh_plugin_map()) == EXPECTED_PLUGINS


def test_urls_are_https_github_clones():
    for name, url in _sh_plugin_map().items():
        assert re.fullmatch(
            r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git", url
        ), f"{name}: malformed clone URL {url!r}"


def test_check_mode_covers_all_plugins():
    sh_check = re.search(r"for name in ([a-z0-9_ ]+); do", INSTALL_SH)
    assert sh_check, "install.sh --check plugin loop not found"
    assert set(sh_check.group(1).split()) == EXPECTED_PLUGINS

    ps_check = re.search(
        r'\$repos = @\("([a-z0-9_",\s]+)"\)', INSTALL_PS1
    )
    assert ps_check, "install.ps1 -Check repo list not found"
    assert set(re.findall(r'"([a-z0-9_]+)"', ps_check.group(0))) == EXPECTED_PLUGINS


def test_config_merge_activates_all_plugins():
    for name in EXPECTED_PLUGINS:
        assert f'"{name}": {{"enabled": True}}' in INSTALL_SH, (
            f"install.sh config merge missing {name}"
        )
        assert re.search(
            rf"{name}\s*=\s*@{{\s*enabled = \$true \s*}}", INSTALL_PS1
        ), f"install.ps1 default config missing {name}"


def test_extracted_skills_not_stale_in_lazyothers():
    """분리된 스킬이 lazyothers에 중복으로 남아 있지 않아야 한다."""
    skills_dir = REPO_ROOT / "skills"
    assert not (skills_dir / "diagram-design").exists(), (
        "diagram-design must live only in the lazydiagram plugin repo"
    )


def test_local_skills_have_skill_md():
    """남은 스킬 디렉터리는 SKILL.md를 갖춰야 한다(플러그인 매니페스트 무결성)."""
    for skill in sorted((REPO_ROOT / "skills").iterdir()):
        if skill.is_dir() and not skill.name.startswith("."):
            assert (skill / "SKILL.md").is_file(), f"{skill.name} lacks SKILL.md"
