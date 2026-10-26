"""deploy_lock in scripts/lib.sh: backup.sh and restore.sh hold the pull agent's lock while services are stopped.

A Python fcntl.flock on the same file stands in for the agent (homelab-pull takes it with `flock --nonblock`; both
are flock(2) locks).
"""

import fcntl
import os
import shutil
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib.sh"
BASH = shutil.which("bash") or "/bin/bash"
STACK = "mnemosyne"
WAITING = "Waiting for a deploy by the pull agent to finish (up to 1800 s)\n"
needs_flock = pytest.mark.skipif(
    shutil.which("flock") is None, reason="flock isn't installed (util-linux), as on macOS"
)


def script(then: str, *, before: str = "") -> str:
    """Shell code that sources lib.sh, calls deploy_lock as backup.sh does (set -e), then runs `then`."""
    return f'set -euo pipefail; . "{LIB}"; {before} deploy_lock; {then}'


def environment(**variables: str) -> dict[str, str]:
    """This process's environment without the agent's variables, plus `variables`."""
    env = {k: v for k, v in os.environ.items() if k not in {"HOMELAB_PULL_STATE_DIR", "XDG_STATE_HOME"}}
    return env | variables


def run(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # The code is this test's own text and lib.sh from the checkout.
    return subprocess.run([BASH, "-c", code], env=env, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603


def start(code: str, env: dict[str, str]) -> subprocess.Popen[str]:
    return subprocess.Popen(  # noqa: S603 # the test's own code, as in run()
        [BASH, "-c", code],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def take(file: object) -> None:
    """Hold the agent's lock on the open lock file, as homelab-pull does during a deploy (released on close)."""
    fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)


def is_locked(lock: Path) -> bool:
    with lock.open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(file, fcntl.LOCK_UN)
        return False


@pytest.fixture
def state(tmp_path: Path) -> Path:
    """The agent's state root with this stack's directory in it."""
    (tmp_path / STACK).mkdir()
    return tmp_path


@pytest.mark.parametrize("variable", ["HOMELAB_PULL_STATE_DIR", "XDG_STATE_HOME", "HOME"])
def test_no_agent_state_does_nothing(tmp_path: Path, variable: str) -> None:
    # Without the agent's state directory nothing is locked or created, flock or not (PATH has no flock here).
    env = environment(**{variable: str(tmp_path), "PATH": str(tmp_path / "bin")})
    result = run(script("echo done"), env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "done\n"
    assert list(tmp_path.iterdir()) == []


def test_agent_state_without_flock_fails(state: Path) -> None:
    result = run(script("echo ran"), environment(HOMELAB_PULL_STATE_DIR=str(state), PATH=str(state / "bin")))
    assert result.returncode == 1
    assert "flock isn't installed" in result.stderr
    assert result.stdout == ""


@needs_flock
@pytest.mark.parametrize("variable", ["HOMELAB_PULL_STATE_DIR", "XDG_STATE_HOME"])
def test_lock_is_held_until_the_script_exits(tmp_path: Path, variable: str) -> None:
    root = tmp_path if variable == "HOMELAB_PULL_STATE_DIR" else tmp_path / "homelab-pull"
    (root / STACK).mkdir(parents=True)
    lock = root / STACK / "lock"
    backup = start(script("echo locked; read -r _"), environment(**{variable: str(tmp_path)}))
    assert backup.stdout is not None
    assert backup.stdout.readline() == "locked\n"
    assert is_locked(lock)
    out, err = backup.communicate(input="\n", timeout=20)
    assert backup.returncode == 0, err
    assert out == ""
    assert not is_locked(lock)


@needs_flock
def test_waits_for_a_running_deploy(state: Path) -> None:
    with (state / STACK / "lock").open("a") as agent:
        take(agent)
        backup = start(script("echo locked"), environment(HOMELAB_PULL_STATE_DIR=str(state)))
        assert backup.stdout is not None
        assert backup.stdout.readline() == WAITING
        assert backup.poll() is None
    out, err = backup.communicate(timeout=20)
    assert backup.returncode == 0, err
    assert out == "locked\n"


@needs_flock
def test_gives_up_after_the_timeout_and_runs_nothing_after(state: Path) -> None:
    with (state / STACK / "lock").open("a") as agent:
        take(agent)
        result = run(
            script("echo ran", before="deploy_lock_timeout=1;"), environment(HOMELAB_PULL_STATE_DIR=str(state))
        )
    assert result.returncode == 1
    assert result.stdout == "Waiting for a deploy by the pull agent to finish (up to 1 s)\n"
    assert f"deploy of {STACK} still holds" in result.stderr
    assert "nothing was stopped" in result.stderr
