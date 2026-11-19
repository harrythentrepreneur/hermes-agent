from pathlib import Path
import os
import shutil
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "setup-hermes.sh"


def _prepare_fake_uv_env(tmp_path: Path, sync_exit_code: int) -> tuple[Path, Path, dict[str, str]]:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    shutil.copy2(SETUP_SCRIPT, checkout / "setup-hermes.sh")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls_log = tmp_path / "uv-calls.log"

    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        f"""#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{calls_log}"
case "${{1:-}}" in
  --version)
    echo "uv 0.13.5"
    exit 0
    ;;
  python)
    if [ "${{2:-}}" = "find" ]; then
      echo "/usr/bin/python3"
      exit 0
    fi
    exit 0
    ;;
  venv)
    mkdir -p "$2/bin"
    printf '#!/bin/sh\\necho Python 3.11.0\\n' > "$2/bin/python"
    chmod +x "$2/bin/python"
    exit 0
    ;;
  sync)
    exit {sync_exit_code}
    ;;
  pip)
    echo "UNEXPECTED_UV_PIP_FALLBACK" >&2
    exit 99
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = os.environ.copy()
    env.pop("TERMUX_VERSION", None)
    env.pop("PREFIX", None)
    env["HOME"] = str(tmp_path / "home")
    Path(env["HOME"]).mkdir()
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    return checkout, calls_log, env


def test_setup_hermes_script_is_valid_shell():
    result = subprocess.run(["bash", "-n", str(SETUP_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_setup_hermes_script_has_termux_path():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "is_termux()" in content
    assert ".[termux]" in content
    assert "constraints-termux.txt" in content
    assert "$PREFIX/bin" in content


def test_setup_hermes_has_no_unhashed_uv_pip_fallback():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")
    assert "_try_install" not in content
    assert "$UV_CMD pip install" not in content


def test_setup_hermes_aborts_nonzero_when_uv_lock_missing(tmp_path: Path):
    checkout, calls_log, env = _prepare_fake_uv_env(tmp_path, sync_exit_code=0)
    result = subprocess.run(
        ["bash", str(checkout / "setup-hermes.sh")],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "uv.lock not found" in (result.stdout + result.stderr)
    logged = calls_log.read_text(encoding="utf-8") if calls_log.exists() else ""
    assert "pip install" not in logged


def test_setup_hermes_aborts_nonzero_when_locked_sync_fails(tmp_path: Path):
    checkout, calls_log, env = _prepare_fake_uv_env(tmp_path, sync_exit_code=2)
    (checkout / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(checkout / "setup-hermes.sh")],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "UNEXPECTED_UV_PIP_FALLBACK" not in (result.stdout + result.stderr)
    logged = calls_log.read_text(encoding="utf-8")
    assert "sync --extra all --locked" in logged
    assert "pip install" not in logged
