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
    {"name": "mariadb:11.8.9-noble", "watch_repo": True, "include_tags": [r"^11\.8\.[0-9]+-noble$"]},
]
RENOVATE = {
    "packageRules": [
        {"matchManagers": ["github-actions"], "matchUpdateTypes": ["minor", "patch"], "groupName": "actions"},
        {"matchPackageNames": ["crazymax/diun"], "matchUpdateTypes": ["major"], "enabled": False},
        {
            "description": "the engines",
            "matchDatasources": ["docker"],
            "matchPackageNames": ["postgres", "mariadb"],
            "enabled": False,
        },
    ]
}
MARIADB_NOT_DISABLED = ["mariadb: [renovate] renovate.json doesn't disable mariadb for every update type"]


def problems(compose: dict | None = None, watches: list | None = None, renovate: dict | None = None) -> list[str]:
    return cw.check(
        compose if compose is not None else COMPOSE,
        watches if watches is not None else WATCHES,
        renovate if renovate is not None else RENOVATE,
    )


def with_rules(*rules: dict) -> dict:
    return {"packageRules": [*RENOVATE["packageRules"][:2], *rules]}


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
    watches[0]["name"] = "postgres:18.5-trixie"
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


def test_renovate_isnt_told_about_an_engine() -> None:
    assert problems(renovate=with_rules({"matchPackageNames": ["postgres"], "enabled": False})) == MARIADB_NOT_DISABLED
    assert len(problems(renovate={})) == 2


@pytest.mark.parametrize(
    "narrowing",
    [
        {"matchUpdateTypes": ["major", "minor", "patch"]},
        {"matchCurrentVersion": "<12"},
        {"matchFileNames": ["compose.yaml"]},
        {"matchDatasources": ["github-tags"]},
        {"matchManagers": ["dockerfile"]},
        {"enabled": None},
    ],
)
def test_renovate_would_propose_some_engine_updates(narrowing: dict) -> None:
    rules = [
        {"matchPackageNames": ["postgres"], "enabled": False},
        {"matchPackageNames": ["mariadb"], "enabled": False, **narrowing},
    ]
    assert problems(renovate=with_rules(*rules)) == MARIADB_NOT_DISABLED


@pytest.mark.parametrize("pattern", ["/^mariadb$/", "maria*", "!postgres"])
def test_renovate_pattern_isnt_taken_for_a_name(pattern: str) -> None:
    rule = {"matchPackageNames": ["postgres", pattern], "enabled": False}
    assert problems(renovate=with_rules(rule)) == MARIADB_NOT_DISABLED


def test_renovate_rule_scoped_to_compose_counts() -> None:
    rule = {"matchManagers": ["docker-compose"], "matchPackageNames": ["postgres", "mariadb"], "enabled": False}
    assert problems(renovate=with_rules(rule)) == []


def test_renovate_later_rule_enables_again() -> None:
    renovate = with_rules(RENOVATE["packageRules"][2], {"matchManagers": ["docker-compose"], "enabled": True})
    assert len(problems(renovate=renovate)) == 2


def test_renovate_needs_the_name_as_written() -> None:
    compose = copy.deepcopy(COMPOSE)
    compose["services"]["postgres"]["image"] = "docker.io/library/" + PG
    assert problems(compose=compose) == [
        "postgres: [renovate] renovate.json doesn't disable docker.io/library/postgres for every update type"
    ]


def test_stale_watch() -> None:
    watches = [*WATCHES, {"name": "redis:8.2", "watch_repo": True, "include_tags": ["x"]}]
    assert problems(watches=watches) == [
        "diun/images.yml: [stale] watches docker.io/library/redis, which compose.yaml doesn't pin as an engine"
    ]


def test_package_names() -> None:
    assert cw.package_names("bitnami/postgresql:18", "docker.io/bitnami/postgresql") == {"bitnami/postgresql"}
    assert cw.package_names("ghcr.io/org/db:1@sha256:00", "ghcr.io/org/db") == {"ghcr.io/org/db"}
    assert cw.package_names("localhost:5000/db", "localhost:5000/db") == {"localhost:5000/db"}


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


def test_main_renovate_isnt_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for path, text in {"compose.yaml": "{}", "diun/images.yml": "[]", "renovate.json": "{"}.items():
        (tmp_path / path).parent.mkdir(exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    assert cw.main(["--root", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err
