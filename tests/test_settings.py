import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
CONFIG_ROOT = "${CONFIG_ROOT:?set CONFIG_ROOT in .env}"
# Each service's host mounts under CONFIG_ROOT, as "<folder under CONFIG_ROOT/<service>>:<container path>"; the first
# is its data. Read-only mounts from the checkout (init scripts, Diun's watch list) are listed apart.
APPS = {
    "postgres": ("config:/var/lib/postgresql", "tls:/tls:ro"),
    "mariadb": ("config:/var/lib/mysql",),
    "diun": ("config:/data",),
}
FROM_CHECKOUT = {
    "postgres": ("./initdb/postgres:/docker-entrypoint-initdb.d:ro",),
    "mariadb": ("./initdb/mariadb:/docker-entrypoint-initdb.d:ro",),
    "diun": ("./diun/images.yml:/etc/diun/images.yml:ro",),
}


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def compose() -> dict:
    return yaml.safe_load(read("compose.yaml"))


def test_every_setting_is_in_env_example_and_interfaces() -> None:
    used = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", read("compose.yaml")))
    example = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", read(".env.example"), re.MULTILINE))
    table = re.findall(r"^\| (`[A-Z][^|]*) \|", read("docs/interfaces.md"), re.MULTILINE)
    documented = {name for cell in table for name in re.findall(r"`([A-Z][A-Z0-9_]*)`", cell)}
    # PUID and PGID are read by scripts/db.sh too, and are used in compose.yaml as well.
    assert used == example
    assert used <= documented


def test_each_service_keeps_its_data_in_its_folder_under_config_root() -> None:
    services = compose()["services"]
    for app, mounts in APPS.items():
        expected = [f"{CONFIG_ROOT}/{app}/{mount}" for mount in mounts] + list(FROM_CHECKOUT.get(app, ()))
        assert services[app]["volumes"] == expected


def test_every_service_with_data_is_an_app() -> None:
    for name, service in compose()["services"].items():
        assert not service.get("volumes") or name in APPS, f"{name} mounts data outside CONFIG_ROOT/<app>"


def test_no_named_volumes() -> None:
    config = compose()
    assert "volumes" not in config
    for name, service in config["services"].items():
        for volume in service.get("volumes") or []:
            assert volume.startswith(("/", "${", "./")), f"{name} mounts a named volume: {volume}"


def test_every_secret_is_a_file_under_its_service_folder() -> None:
    pattern = re.escape(CONFIG_ROOT) + r"/[a-z-]+/secrets/[a-z_.]+"
    for name, secret in compose()["secrets"].items():
        assert re.fullmatch(pattern, secret["file"]), name


def test_no_setting_points_into_dockers_volumes() -> None:
    for line in read(".env.example").splitlines():
        assert "/var/lib/docker" not in line.partition("#")[0], line


def test_engines_are_never_restarted_by_autoheal() -> None:
    # A database mid-recovery that is restarted starts its recovery over; restart: unless-stopped covers crashes.
    for name, service in compose()["services"].items():
        assert "autoheal" not in (service.get("labels") or {}), name


def test_superuser_never_logs_in_over_the_network() -> None:
    hba = compose()["services"]["postgres"]["environment"]["PG_HBA"]
    rules = [line.split() for line in hba.splitlines() if line.strip() and not line.startswith("#")]
    first_postgres = next(rule for rule in rules if rule[0].startswith("host") and rule[2] in {"postgres", "all"})
    assert first_postgres == ["host", "all", "postgres", "all", "reject"]
    assert rules[-1] == ["host", "all", "all", "all", "reject"]
    assert not any(rule[-1] == "trust" for rule in rules if rule[0] != "local")


def test_mariadb_root_is_local_only() -> None:
    assert compose()["services"]["mariadb"]["environment"]["MARIADB_ROOT_HOST"] == "localhost"


def test_init_scripts_run_the_way_their_engine_expects() -> None:
    # The postgres entrypoint runs an executable .sh (its `set -eu` stays in its own process); the mariadb one must
    # source its script, because it calls the entrypoint's own docker_process_sql.
    assert (ROOT / "initdb/postgres/10-metrics.sh").stat().st_mode & 0o111
    assert not (ROOT / "initdb/mariadb/10-exporter.sh").stat().st_mode & 0o111
