"""The scripts' argument checks and helpers that need no Docker: each case fails (or answers) before any docker call.

A stand-in `docker` on PATH fails the test if a script reaches it.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
BASH = shutil.which("bash") or "/bin/bash"


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\necho 'docker must not be called' >&2\nexit 99\n", encoding="utf-8")
    docker.chmod(0o755)
    keep = {k: v for k, v in os.environ.items() if not k.startswith(("COMPOSE_", "CONFIG_ROOT", "PUID", "PGID"))}
    return {**keep, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path)}


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, env=env, check=False)  # noqa: S603


def lib(env: dict[str, str], script: str) -> subprocess.CompletedProcess[str]:
    return run(env, BASH, "-c", f'set -euo pipefail\nroot="$1"\n. "$1/scripts/lib.sh"\n{script}', "bash", str(ROOT))


@pytest.mark.parametrize(
    "name",
    ["Sonarr", "sonarr-main", "1radarr", "", "a" * 64, "x;drop", "postgres", "metrics", "root", "information_schema"],
)
def test_db_refuses_bad_or_reserved_names(env: dict[str, str], name: str) -> None:
    result = run(env, str(ROOT / "scripts/db.sh"), "create", "pg", "sonarr", name)
    assert result.returncode == 2
    assert "error:" in result.stderr


def test_db_refuses_unknown_engine(env: dict[str, str]) -> None:
    result = run(env, str(ROOT / "scripts/db.sh"), "create", "oracle", "app", "app_main")
    assert result.returncode == 2
    assert "pg or mariadb" in result.stderr


@pytest.mark.parametrize("args", [(), ("create", "pg", "app"), ("password", "pg"), ("list", "x"), ("nope",)])
def test_db_usage(env: dict[str, str], args: tuple[str, ...]) -> None:
    result = run(env, str(ROOT / "scripts/db.sh"), *args)
    assert result.returncode == 2
    assert "scripts/db.sh init" in result.stderr


def test_db_init_refuses_config_root_in_docker_volumes(env: dict[str, str]) -> None:
    env = {**env, "CONFIG_ROOT": "/var/lib/docker/volumes/x/_data", "PUID": "1000", "PGID": "1000"}
    result = run(env, str(ROOT / "scripts/db.sh"), "init")
    assert result.returncode == 1
    assert "volume prune" in result.stderr


def test_db_init_creates_secrets_once(env: dict[str, str], tmp_path: Path) -> None:
    if shutil.which("openssl") is None:
        pytest.skip("openssl isn't installed")
    config = tmp_path / "config"
    env = {
        **env,
        "CONFIG_ROOT": str(config),
        "PUID": str(os.getuid()),
        "PGID": str(os.getgid()),
        "MNEMOSYNE_DISCORD_WEBHOOK": "https://discord.com/api/webhooks/1/test",
    }
    first = run(env, str(ROOT / "scripts/db.sh"), "init", "--tls-name", "db.example.com")
    assert first.returncode == 0, first.stderr
    password = (config / "postgres/secrets/postgres_password").read_text(encoding="utf-8")
    assert len(password) == 48
    assert (config / "postgres/secrets/postgres_password").stat().st_mode & 0o777 == 0o600
    assert (config / "postgres/secrets").stat().st_mode & 0o777 == 0o700
    exporter = (config / "mariadb/secrets/exporter_password").read_text(encoding="utf-8")
    assert f"password={exporter}" in (config / "mysqld-exporter/secrets/my.cnf").read_text(encoding="utf-8")
    assert (config / "postgres/tls/server.key").stat().st_mode & 0o777 == 0o600
    second = run(env, str(ROOT / "scripts/db.sh"), "init")
    assert second.returncode == 0, second.stderr
    assert "created" not in second.stdout
    assert (config / "postgres/secrets/postgres_password").read_text(encoding="utf-8") == password


def test_db_init_needs_a_webhook(env: dict[str, str], tmp_path: Path) -> None:
    if shutil.which("openssl") is None:
        pytest.skip("openssl isn't installed")
    env = {**env, "CONFIG_ROOT": str(tmp_path / "c"), "PUID": str(os.getuid()), "PGID": str(os.getgid())}
    result = run(env, str(ROOT / "scripts/db.sh"), "init")
    assert result.returncode == 1
    assert "webhook" in result.stderr


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("pg", "Bad-Name"), "isn't a database name"),
        (("pg-roles", "extra"), "scripts/restore.sh DIR pg DB"),
        (("tape", "x"), "scripts/restore.sh DIR pg DB"),
        (("pg", "app", "--force"), "scripts/restore.sh DIR pg DB"),
        (("pg", "app"), "no SHA256SUMS"),
    ],
)
def test_restore_refuses(env: dict[str, str], tmp_path: Path, args: tuple[str, ...], message: str) -> None:
    result = run(env, str(ROOT / "scripts/restore.sh"), str(tmp_path), *args)
    assert result.returncode in {1, 2}
    assert message in result.stderr


def test_restore_refuses_a_damaged_backup(env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "postgres").mkdir()
    (tmp_path / "postgres/app.dump").write_text("dump", encoding="utf-8")
    sums = subprocess.run(  # noqa: S603
        [BASH, "-c", 'cd "$1" && sha256sum postgres/app.dump', "bash", str(tmp_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    (tmp_path / "SHA256SUMS").write_text(sums, encoding="utf-8")
    (tmp_path / "postgres/app.dump").write_text("changed", encoding="utf-8")
    result = run(env, str(ROOT / "scripts/restore.sh"), str(tmp_path), "pg", "app")
    assert result.returncode == 1
    assert "docker must not be called" not in result.stderr


def test_backup_refuses_a_non_empty_directory(env: dict[str, str], tmp_path: Path) -> None:
    (tmp_path / "old").write_text("x", encoding="utf-8")
    result = run(env, str(ROOT / "scripts/backup.sh"), str(tmp_path))
    assert result.returncode == 1
    assert "isn't empty" in result.stderr


@pytest.mark.parametrize(
    ("cidr", "expected"),
    [
        ("192.168.40.0/24", "192.168.40.0/255.255.255.0"),
        ("10.0.0.0/8", "10.0.0.0/255.0.0.0"),
        ("192.168.40.0/22", "192.168.40.0/255.255.252.0"),
        ("172.30.0.0/27", "172.30.0.0/255.255.255.224"),
        ("0.0.0.0/0", "0.0.0.0/0.0.0.0"),
    ],
)
def test_netmask_form(env: dict[str, str], cidr: str, expected: str) -> None:
    result = lib(env, f"netmask_form {cidr}")
    assert result.stdout == expected


@pytest.mark.parametrize("bad", ["192.168.40.0", "192.168.40.0/33", "fd00::/64", "x/24"])
def test_netmask_form_refuses(env: dict[str, str], bad: str) -> None:
    result = lib(env, f"netmask_form {bad}")
    assert result.returncode == 1


def test_setting_from_env_file_and_environment(env: dict[str, str], tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text('PUID=1001\nDB_CLIENT_SUBNET="192.168.40.0/24"\nPUID=1002\n', encoding="utf-8")
    env = {**env, "COMPOSE_ENV_FILES": f"{env_file},{tmp_path}/other"}
    assert lib(env, "setting PUID").stdout == "1002"
    assert lib(env, "setting DB_CLIENT_SUBNET").stdout == "192.168.40.0/24"
    assert lib({**env, "PUID": "7"}, "setting PUID").stdout == "7"
    missing = lib(env, "setting PGID")
    assert missing.returncode == 1
    assert "isn't set" in missing.stderr


def test_setting_without_env_file(env: dict[str, str], tmp_path: Path) -> None:
    result = lib({**env, "COMPOSE_ENV_FILES": str(tmp_path / "none")}, "setting PUID")
    assert result.returncode == 1
    assert "cp .env.example .env" in result.stderr
