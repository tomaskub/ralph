from pathlib import Path


def test_release_script_reads_version_through_uv_python() -> None:
    release_script = Path("scripts/release").read_text()

    assert "uv run python - <<'PY'" in release_script
    assert "  python - <<'PY'" not in release_script


def test_release_script_checks_required_tools_before_releasing() -> None:
    release_script = Path("scripts/release").read_text()

    assert "require_command git" in release_script
    assert "require_command uv" in release_script
    assert "require_command gh" in release_script


def test_release_script_cleanup_trap_can_access_build_dir_at_exit() -> None:
    release_script = Path("scripts/release").read_text()

    assert 'build_dir=""' in release_script
    assert "trap cleanup EXIT" in release_script
    assert 'trap \'rm -rf "$build_dir"\' EXIT' not in release_script


def test_release_script_uses_bare_semver_tags() -> None:
    release_script = Path("scripts/release").read_text()

    assert 'tag="$version"' in release_script
    assert 'tag="v$version"' not in release_script
