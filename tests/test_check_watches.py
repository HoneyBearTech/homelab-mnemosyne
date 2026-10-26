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
DEPENDABOT = {
    "updates": [
        {"package-ecosystem": "pip"},
        {
            "package-ecosystem": "docker-compose",
            "ignore": [
                {"dependency-name": "postgres"},
                {"dependency-name": "mariadb"},
                {"dependency-name": "crazymax/diun", "update-types": ["version-update:semver-major"]},
            ],
        },
    ]
}


def problems(compose: dict | None = None, watches: list | None = None, dependabot: dict | None = None) -> list[str]:
    return cw.check(
        compose if compose is not None else COMPOSE,
        watches if watches is not None else WATCHES,
        dependabot if dependabot is not None else DEPENDABOT,
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


def test_dependabot_would_propose_an_engine() -> None:
    dependabot = copy.deepcopy(DEPENDABOT)
    dependabot["updates"][1]["ignore"][1] = {
        "dependency-name": "mariadb",
        "update-types": ["version-update:semver-major"],
    }
    assert problems(dependabot=dependabot) == [
        "mariadb: [dependabot] .github/dependabot.yml doesn't ignore mariadb for every update type"
    ]


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
    (tmp_path / ".github").mkdir()
    (tmp_path / "compose.yaml").write_text((ROOT / "compose.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "diun" / "images.yml").write_text("[]\n", encoding="utf-8")
    (tmp_path / ".github" / "dependabot.yml").write_text("updates: []\n", encoding="utf-8")
    assert cw.main(["--root", str(tmp_path)]) == 1
    assert "2 engine(s) checked, 4 problem(s)" in capsys.readouterr().out


def test_main_unreadable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cw.main(["--root", str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


def test_main_wrong_shape(tmp_path: Path) -> None:
    for path, text in {"compose.yaml": "[]", "diun/images.yml": "[]", ".github/dependabot.yml": "{}"}.items():
        (tmp_path / path).parent.mkdir(exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    assert cw.main(["--root", str(tmp_path)]) == 2
