"""Check that every database engine compose.yaml pins is watched by Diun, and left alone by Dependabot.

The engines are moved by hand (docs/upgrading.md): Dependabot must not propose them, and Diun's alerts are the
only way a new release reaches the owner. So a pin that Diun doesn't watch, or watches at another tag, would go
quiet. An engine is a service with the label ``org.honeybeartech.mnemosyne.engine``. Rules:

- ``watched``: diun/images.yml has exactly one entry for the engine's image repository.
- ``pinned-tag``: that entry's name carries the tag compose.yaml pins (so the rebuild of that tag is watched).
- ``watch-repo``: the entry watches the repository's tags (``watch_repo: true``) with ``include_tags``.
- ``include``: one of ``include_tags`` matches the pinned tag (a pattern that doesn't is a typo, and would likely
  miss the next release too).
- ``stale``: no entry watches an image that compose.yaml doesn't pin as an engine.
- ``dependabot``: .github/dependabot.yml ignores the engine for every update type.

Exit codes: 0 = consistent, 1 = problems, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from check_compose import ImageRef, parse_image

ENGINE_LABEL = "org.honeybeartech.mnemosyne.engine"
ROOT = Path(__file__).resolve().parent.parent


def engines(compose: dict[str, Any]) -> dict[str, str]:
    """Return the engines' pinned images, as {service: image}."""
    found = {}
    for name, service in (compose.get("services") or {}).items():
        labels = service.get("labels") or {}
        if isinstance(labels, list):
            labels = dict(str(item).partition("=")[::2] for item in labels)
        if ENGINE_LABEL in labels:
            found[name] = str(service.get("image", ""))
    return found


def ignored_by_dependabot(dependabot: dict[str, Any]) -> set[str]:
    """Return the dependency names the docker-compose ecosystem ignores for every update type."""
    names = set()
    for update in dependabot.get("updates") or []:
        if update.get("package-ecosystem") != "docker-compose":
            continue
        for rule in update.get("ignore") or []:
            if not rule.get("update-types") and not rule.get("versions"):
                names.add(str(rule.get("dependency-name", "")))
    return names


def dependency_name(repository: str) -> str:
    """Dependabot's name for an image: Docker Hub's official images without docker.io/library/."""
    return repository.removeprefix("docker.io/library/").removeprefix("docker.io/")


def watch_problems(service: str, pin: ImageRef, watches: list[dict[str, Any]]) -> list[str]:
    """Return the problems with one engine's entry in diun/images.yml."""
    entries = [w for w in watches if parse_image(str(w.get("name", ""))).repository == pin.repository]
    if len(entries) != 1:
        return [f"{service}: [watched] {len(entries)} entries in diun/images.yml for {pin.repository}, not 1"]
    entry = entries[0]
    problems = []
    watched_tag = parse_image(str(entry["name"])).tag
    if watched_tag != pin.tag:
        problems.append(f"{service}: [pinned-tag] diun/images.yml watches {watched_tag}, compose.yaml pins {pin.tag}")
    patterns = entry.get("include_tags") or []
    if entry.get("watch_repo") is not True or not patterns:
        problems.append(f"{service}: [watch-repo] the entry needs watch_repo: true and include_tags")
    elif not any(re.search(str(p), pin.tag or "") for p in patterns):
        problems.append(f"{service}: [include] no include_tags pattern matches the pinned tag {pin.tag}")
    return problems


def check_engine(service: str, image: str, watches: list[dict[str, Any]], ignored: set[str]) -> list[str]:
    """Return the problems with one engine's watch and Dependabot rule."""
    pin = parse_image(image)
    problems = watch_problems(service, pin, watches)
    if dependency_name(pin.repository) not in ignored:
        problems.append(
            f"{service}: [dependabot] .github/dependabot.yml doesn't ignore {dependency_name(pin.repository)} "
            "for every update type"
        )
    return problems


def check(compose: dict[str, Any], watches: list[dict[str, Any]], dependabot: dict[str, Any]) -> list[str]:
    """Every problem, engine by engine, then the stale watches."""
    pinned = engines(compose)
    ignored = ignored_by_dependabot(dependabot)
    problems = []
    for service, image in sorted(pinned.items()):
        problems += check_engine(service, image, watches, ignored)
    repositories = {parse_image(image).repository for image in pinned.values()}
    for entry in watches:
        repository = parse_image(str(entry.get("name", ""))).repository
        if repository not in repositories:
            problems.append(
                f"diun/images.yml: [stale] watches {repository}, which compose.yaml doesn't pin as an engine"
            )
    return problems


def load(path: Path) -> Any:  # noqa: ANN401 # YAML documents are whatever the file holds
    """Read a YAML file."""
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    """Run the check; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout (default: this script's)")
    args = parser.parse_args(argv)
    try:
        compose = load(args.root / "compose.yaml")
        watches = load(args.root / "diun" / "images.yml")
        dependabot = load(args.root / ".github" / "dependabot.yml")
    except (OSError, yaml.YAMLError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    if not isinstance(compose, dict) or not isinstance(watches, list) or not isinstance(dependabot, dict):
        print("error: compose.yaml, diun/images.yml or .github/dependabot.yml isn't what it should be", file=sys.stderr)
        return 2
    problems = check(compose, watches, dependabot)
    for problem in problems:
        print(problem)
    print(f"{len(engines(compose))} engine(s) checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
