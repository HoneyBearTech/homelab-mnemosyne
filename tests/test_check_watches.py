import copy
from pathlib import Path

import check_watches as cw
import pytest

ROOT = Path(__file__).parent.parent
PG = "postgres:18.6-trixie@sha256:" + "a" * 64
MARIA = "mariadb:11.8.9-noble@sha256:" + "b" * 64
COMPOSE = {
    "services": {
        "postgres": {"image": PG, "labels": {cw.ENGINE_LABEL: "postgres"}},
        "mariadb": {"image": MARIA, "labels": [f"{cw.ENGINE_LABEL}=mariadb"]},
        "diun": {"image": "crazymax/diun:4.33.1@sha256:" + "c" * 64},
    }
}
WATCHES = [
    {"name": "docker.io/library/postgres:18.6-trixie", "watch_repo": True, "include_tags": [r"^18\.[0-9]+-trixie$"]},
    {"name": "docker.io/library/mariadb:11.8.9-noble", "watch_repo": True, "include_tags": [r"^11\.8\.[0-9]+-noble$"]},
]
DIUN_MANAGER = {
    "customType": "regex",
    "managerFilePatterns": ["/^diun/images\\.yml$/"],
    "matchStrings": [
        (
            r"(?:^|\n)- name: docker\.io/library/(?<depName>postgres|mariadb):(?<currentValue>[A-Za-z0-9._-]+)"
            r"[ \t]*(?:\n|$)"
        )
    ],
    "datasourceTemplate": "docker",
}
RENOVATE = {
    "extends": ["config:recommended"],
    "enabledManagers": ["docker-compose", "custom.regex"],
    "automerge": True,
    "customManagers": [DIUN_MANAGER],
    "packageRules": [
        {
            "matchPackageNames": ["postgres", "mariadb"],
            "matchUpdateTypes": ["major"],
            "dependencyDashboardApproval": True,
        },
        {"matchPackageNames": ["crazymax/diun"], "automerge": True},
        {"matchPackageNames": ["postgres", "mariadb"], "automerge": False, "prBodyNotes": ["by hand"]},
    ],
}


def problems(compose: dict | None = None, watches: list | None = None, renovate: dict | None = None) -> list[str]:
    return cw.check(
        compose if compose is not None else COMPOSE,
        watches if watches is not None else WATCHES,
        renovate if renovate is not None else RENOVATE,
    )


def test_consistent() -> None:
    assert problems() == []


def test_engines_by_label_in_either_form() -> None:
    assert cw.engines(COMPOSE) == {"postgres": PG, "mariadb": MARIA}


def test_unwatched_engine() -> None:
    assert problems(watches=WATCHES[1:]) == [
        "postgres: [watched] 0 entries in diun/images.yml for docker.io/library/postgres, not 1"
    ]


def test_watched_twice() -> None:
    assert "[watched] 2 entries" in problems(watches=[*WATCHES, WATCHES[0]])[0]


def test_watch_at_another_tag() -> None:
    watches = copy.deepcopy(WATCHES)
    watches[0]["name"] = "docker.io/library/postgres:18.5-trixie"
    assert problems(watches=watches) == [
        "postgres: [pinned-tag] diun/images.yml watches 18.5-trixie, compose.yaml pins 18.6-trixie"
    ]


@pytest.mark.parametrize("change", [{"watch_repo": False}, {"include_tags": []}])
def test_not_watching_the_repository(change: dict) -> None:
    watches = copy.deepcopy(WATCHES)
    watches[1].update(change)
    assert problems(watches=watches) == ["mariadb: [watch-repo] the entry needs watch_repo: true and include_tags"]


def test_patterns_miss_the_pin() -> None:
    watches = copy.deepcopy(WATCHES)
    watches[0]["include_tags"] = [r"^18\.[0-9]+-bookworm$"]
    assert problems(watches=watches) == [
        "postgres: [include] no include_tags pattern matches the pinned tag 18.6-trixie"
    ]


def renovate_with(**changes: object) -> dict:
    renovate = copy.deepcopy(RENOVATE)
    renovate.update(changes)
    return renovate


def with_rules(rules: list[dict]) -> dict:
    return renovate_with(packageRules=copy.deepcopy(rules))


HOLD = RENOVATE["packageRules"][-1]
HOLD_PROBLEM = "[renovate] the last packageRule must be the {} rule: only the keys"


def hold_with(**changes: object) -> dict:
    return with_rules([*RENOVATE["packageRules"][:-1], {**HOLD, **changes}])


def test_the_hold_is_not_the_last_rule() -> None:
    later = {"matchPackageNames": ["crazymax/diun"], "automerge": True}
    found = problems(renovate=with_rules([*RENOVATE["packageRules"], later]))
    assert [p.split(" ")[0] for p in found] == ["mariadb:", "postgres:"]
    assert all(HOLD_PROBLEM.format(p.split(":")[0]) in p for p in found)


def test_no_package_rules_at_all() -> None:
    assert len(problems(renovate={**RENOVATE, "packageRules": []})) == 2
    assert len(problems(renovate={**RENOVATE, "packageRules": "nope"})) == 2


def test_a_hold_that_names_only_one_engine() -> None:
    found = problems(renovate=hold_with(matchPackageNames=["postgres"]))
    assert len(found) == 1
    assert found[0].startswith("mariadb: ")


@pytest.mark.parametrize(
    "change",
    [
        {"matchDepNames": ["mariadb"]},
        {"matchDepNames": []},
        {"matchUpdateTypes": []},
        {"matchUpdateTypes": ["minor", "patch"]},
        {"matchPackageNames": ["postgres", "mariadb"], "matchManagers": ["docker-compose"]},
        {"matchPackagePatterns": ["maria"]},
        {"enabled": True},
        {"enabled": False},
        {"groupName": "engines"},
        {"automerge": True},
        {"automerge": None},
        {"automerge": "false"},
        {"matchPackageNames": ["MARIADB", "postgres"]},
        {"matchPackageNames": ["{postgres,mariadb}"]},
        {"matchPackageNames": ["@(postgres|mariadb)"]},
        {"matchPackageNames": ["postgres", "mariadb", "mar*"]},
        {"matchPackageNames": ["postgres", "mariadb", "!x"]},
        {"matchPackageNames": ["/^(postgres|mariadb)$/g"]},
        {"matchPackageNames": ["/^(postgres|mariadb)$/i"]},
        {"matchPackageNames": ["docker.io/library/postgres", "docker.io/library/mariadb"]},
        {"matchPackageNames": "mariadb"},
        {"matchPackageNames": [["mariadb"]]},
        {"matchPackageNames": []},
    ],
)
def test_a_hold_that_isnt_a_strict_hold(change: dict) -> None:
    found = problems(renovate=hold_with(**change))
    assert found
    assert any("[renovate] the last packageRule must be the" in p for p in found)


def test_a_hold_that_is_a_plain_list_with_extra_names_passes() -> None:
    assert problems(renovate=hold_with(matchPackageNames=["postgres", "mariadb", "other-thing_1.x"])) == []


def test_a_non_object_as_the_last_rule() -> None:
    assert len(problems(renovate=with_rules([*RENOVATE["packageRules"][:-1], "mariadb"]))) == 2


@pytest.mark.parametrize(
    "rule",
    [
        {"enabled": False},
        {"enabled": False, "matchUpdateTypes": ["major"]},
        {"enabled": False, "matchManagers": ["docker-compose"]},
        {"enabled": False, "matchDatasources": []},
        {"enabled": False, "matchDatasources": ["docker"]},
        {"enabled": False, "matchPackageNames": []},
        {"enabled": False, "matchPackageNames": ["mariadb"]},
        {"enabled": False, "matchPackageNames": ["MariaDB"]},
        {"enabled": False, "matchDepNames": ["postgres"]},
        {"enabled": False, "matchPackageNames": ["maria*"]},
        {"enabled": False, "matchPackageNames": ["/^maria/"]},
        {"enabled": False, "matchPackageNames": ["{postgres,x}"]},
        {"enabled": False, "matchPackageNames": ["!other"]},
    ],
)
def test_a_rule_that_could_disable_an_engine(rule: dict) -> None:
    found = problems(renovate=with_rules([rule, *RENOVATE["packageRules"]]))
    assert found
    assert all("packageRules[0] disables updates and could include" in p for p in found)


@pytest.mark.parametrize(
    "rule",
    [
        {"enabled": False, "matchDatasources": ["github-runners"]},
        {"enabled": False, "matchPackageNames": ["python", "actions/python-versions"], "matchUpdateTypes": ["major"]},
        {"enabled": False, "matchDepNames": ["dependabot/fetch-metadata"]},
        {"enabled": True, "matchManagers": ["docker-compose"]},
        {"automerge": True},
    ],
)
def test_a_rule_that_cannot_disable_an_engine(rule: dict) -> None:
    assert problems(renovate=with_rules([rule, *RENOVATE["packageRules"]])) == []


@pytest.mark.parametrize("preset", [":automergeAll", ":automergeDisabled", "group:allNonMajor", "config:base"])
def test_an_extends_preset_that_isnt_known(preset: str) -> None:
    found = problems(renovate=renovate_with(extends=["config:recommended", preset]))
    assert len(found) == 2
    assert all(f"[renovate] extends has {preset}, which this check doesn't know" in p for p in found)


@pytest.mark.parametrize(
    "alerts",
    [
        {"automerge": True},
        {"automerge": False},
        {"extends": [":automergeAll"]},
        {"packageRules": [{"automerge": True}]},
        {"labels": ["security"], "schedule": ["at any time"]},
        True,
        [],
    ],
)
def test_vulnerability_alerts_that_are_more_than_labels(alerts: object) -> None:
    found = problems(renovate=renovate_with(vulnerabilityAlerts=alerts))
    assert len(found) == 2
    assert all("[renovate] vulnerabilityAlerts may only set labels" in p for p in found)


def test_vulnerability_alerts_with_labels_only() -> None:
    assert problems(renovate=renovate_with(vulnerabilityAlerts={"labels": ["security"]})) == []
    assert problems(renovate=renovate_with(vulnerabilityAlerts={})) == []


def test_osv_vulnerability_alerts_must_be_a_boolean() -> None:
    assert problems(renovate=renovate_with(osvVulnerabilityAlerts=True)) == []
    found = problems(renovate=renovate_with(osvVulnerabilityAlerts={"automerge": True}))
    assert len(found) == 2
    assert all("osvVulnerabilityAlerts must be true or false" in p for p in found)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"enabled": False}, "Renovate is disabled"),
        ({"ignoreDeps": ["mariadb"]}, "ignoreDeps has mariadb"),
        ({"enabledManagers": ["github-actions", "custom.regex"]}, "enabledManagers must include"),
        ({"enabledManagers": ["docker-compose"]}, "enabledManagers must include"),
        ({"docker-compose": {"enabled": False}}, '"docker-compose" is disabled'),
        ({"custom.regex": {"enabled": False}}, '"custom.regex" is disabled'),
        ({"customManagers": [{**DIUN_MANAGER, "enabled": False}]}, "a customManagers entry is disabled"),
    ],
)
def test_renovate_is_told_to_ignore_an_engine(change: dict, message: str) -> None:
    found = problems(renovate=renovate_with(**change))
    assert any(f"[renovate] {message}" in p for p in found)


def test_harmless_settings_are_allowed() -> None:
    harmless = {"docker-compose": {"enabled": True}, "ignoreDeps": ["other"], "customManagers": [DIUN_MANAGER]}
    assert problems(renovate=renovate_with(**harmless)) == []


@pytest.mark.parametrize(
    "change",
    [
        {"customManagers": []},
        {"customManagers": [{**DIUN_MANAGER, "customType": "jsonata"}]},
        {"customManagers": [{**DIUN_MANAGER, "managerFilePatterns": ["/^other\\.yml$/"]}]},
        {"customManagers": [{**DIUN_MANAGER, "datasourceTemplate": "pypi"}]},
        {"customManagers": [{**DIUN_MANAGER, "matchStrings": [r"- name: (?<depName>nothing):(?<currentValue>\S+)"]}]},
        {"customManagers": [{**DIUN_MANAGER, "matchStrings": [r"- name: .*(?<depName>mariadb):(?<currentValue>\d+)"]}]},
    ],
)
def test_no_manager_reads_the_diun_tags(change: dict) -> None:
    found = problems(renovate=renovate_with(**change))
    assert len(found) == 2
    assert all("[diun-manager]" in p for p in found)


def test_stale_watch() -> None:
    watches = [*WATCHES, {"name": "redis:8.2", "watch_repo": True, "include_tags": ["x"]}]
    assert problems(watches=watches) == [
        "diun/images.yml: [stale] watches docker.io/library/redis, which compose.yaml doesn't pin as an engine"
    ]


def test_dependency_name_of_a_namespaced_image() -> None:
    assert cw.dependency_name("docker.io/bitnami/postgresql") == "bitnami/postgresql"


def test_the_repository_itself_is_consistent(capsys: pytest.CaptureFixture[str]) -> None:
    assert cw.main(["--root", str(ROOT)]) == 0
    assert "2 engine(s) checked, 0 problem(s)" in capsys.readouterr().out


def test_main_reports_problems(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "diun").mkdir()
    (tmp_path / "compose.yaml").write_text((ROOT / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "diun" / "images.yml").write_text("[]\n", encoding="utf-8")
    (tmp_path / "renovate.json").write_text("{}\n", encoding="utf-8")
    assert cw.main(["--root", str(tmp_path)]) == 1
    assert "2 engine(s) checked, 4 problem(s)" in capsys.readouterr().out


def test_main_unreadable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cw.main(["--root", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


def test_main_wrong_shape(tmp_path: Path) -> None:
    for path, text in {"compose.yaml": "[]", "diun/images.yml": "[]", "renovate.json": "{}"}.items():
        (tmp_path / path).parent.mkdir(exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    assert cw.main(["--root", str(tmp_path)]) == 2


def test_main_renovate_json_that_is_not_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for path in ("compose.yaml", "diun/images.yml"):
        (tmp_path / path).parent.mkdir(exist_ok=True)
        (tmp_path / path).write_text("[]" if path.endswith("yml") else "{}", encoding="utf-8")
    (tmp_path / "renovate.json").write_text("{ // a comment\n}", encoding="utf-8")
    assert cw.main(["--root", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err
