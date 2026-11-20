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


MARIADB_HOLD = {"matchPackageNames": ["mariadb"], "automerge": False}
NO_RULE = "mariadb: [renovate] renovate.json has no packageRule that names mariadb and sets automerge: false"


def test_no_rule_holds_the_engine() -> None:
    rules = [r for r in RENOVATE["packageRules"] if r.get("automerge") is not False]
    assert [p for p in problems(renovate=with_rules(rules)) if p.startswith("mariadb")] == [
        NO_RULE + " with no other matcher (such as matchUpdateTypes)"
    ]


def test_a_hold_that_names_only_one_engine() -> None:
    rules = [*RENOVATE["packageRules"][:2], {"matchPackageNames": ["postgres"], "automerge": False}]
    assert len(problems(renovate=with_rules(rules))) == 1


def test_a_hold_narrowed_to_some_updates() -> None:
    hold = {**MARIADB_HOLD, "matchUpdateTypes": ["minor", "patch", "digest"]}
    assert NO_RULE in problems(renovate=with_rules([{"matchPackageNames": ["postgres"], "automerge": False}, hold]))[0]


def test_a_hold_that_is_disabled_or_negated() -> None:
    for hold in ({**MARIADB_HOLD, "enabled": False}, {"matchPackageNames": ["mariadb", "!foo"], "automerge": False}):
        assert any(NO_RULE in p for p in problems(renovate=with_rules([hold])))


@pytest.mark.parametrize(
    "later",
    [
        {"automerge": True},
        {"matchManagers": ["docker-compose"], "automerge": True},
        {"matchPackageNames": ["!crazymax/diun"], "automerge": True},
        {"matchPackageNames": ["maria*"], "automerge": True},
        {"matchPackageNames": ["/^maria/"], "automerge": True},
        {"matchPackagePatterns": ["^mar"], "automerge": True},
        {"matchPackageNames": ["MARIADB"], "automerge": True},
        {"matchPackageNames": ["/^MARIADB$/i"], "automerge": True},
        {"matchPackageNames": ["/^(/"], "automerge": True},
        {"matchPackageNames": ["mariadb"], "matchDepNames": ["MariaDB"], "automerge": True},
    ],
)
def test_a_later_rule_could_turn_automerge_back_on(later: dict) -> None:
    found = problems(renovate=with_rules([*RENOVATE["packageRules"], later]))
    assert found
    assert all("packageRules[3] comes after the" in p and "turn automerge back on" in p for p in found)


@pytest.mark.parametrize(
    "later",
    [
        {"matchPackageNames": ["crazymax/diun"], "automerge": True},
        {"matchPackageNames": ["/^prom/"], "automerge": True},
        {"matchPackageNames": ["/^MARIADB$/"], "automerge": True},
        {"matchPackageNames": ["mariadb"], "matchDepNames": ["crazymax/diun"], "automerge": True},
        {"matchPackageNames": ["mariadb"], "dependencyDashboardApproval": True},
        {"automerge": False},
    ],
)
def test_a_later_rule_that_cannot_matter(later: dict) -> None:
    assert problems(renovate=with_rules([*RENOVATE["packageRules"], later])) == []


def test_a_preset_turns_automerge_on() -> None:
    assert problems(renovate=renovate_with(extends=["config:recommended", ":automergeAll"])) == [
        "mariadb: [renovate] the extends preset :automergeAll turns automerge on",
        "postgres: [renovate] the extends preset :automergeAll turns automerge on",
    ]
    assert problems(renovate=renovate_with(extends=[":automergeDisabled"])) == []


@pytest.mark.parametrize(
    "change",
    [
        {"ignoreDeps": ["mariadb"]},
        {"enabled": False},
        {"enabledManagers": ["github-actions"]},
        {"packageRules": [*RENOVATE["packageRules"], {"matchPackageNames": ["mariadb"], "enabled": False}]},
    ],
)
def test_renovate_is_told_to_ignore_an_engine(change: dict) -> None:
    found = problems(renovate=renovate_with(**change))
    assert any("[renovate] renovate.json tells Renovate to ignore or disable" in p for p in found)


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


def test_a_hold_with_two_name_matchers_must_cover_the_engine_with_each() -> None:
    hold = {"matchPackageNames": ["postgres", "mariadb"], "matchDepNames": ["mariadb"], "automerge": False}
    found = problems(renovate=with_rules([hold]))
    assert len(found) == 1
    assert found[0].startswith("postgres: [renovate] renovate.json has no packageRule that names postgres")
    both = {**hold, "matchDepNames": ["postgres", "MariaDB"]}
    assert problems(renovate=with_rules([both])) == []


def test_a_hold_with_a_case_insensitive_regex_or_glob() -> None:
    assert problems(renovate=with_rules([{"matchPackageNames": ["/^(postgres|mariadb)$/i"], "automerge": False}])) == []
    assert problems(renovate=with_rules([{"matchPackageNames": ["Maria*", "POSTGRES"], "automerge": False}])) == []


def test_vulnerability_alerts_that_automerge() -> None:
    found = problems(renovate=renovate_with(vulnerabilityAlerts={"automerge": True}))
    assert [p.split(":")[0] for p in found] == ["mariadb", "postgres"]
    assert all("[renovate] vulnerabilityAlerts sets automerge: true" in p for p in found)
    assert problems(renovate=renovate_with(vulnerabilityAlerts={"labels": ["security"]})) == []
