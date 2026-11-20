"""Check that every database engine compose.yaml pins is watched by Diun, and never merged by Renovate.

The engines are merged by hand at a quiet time (docs/upgrading.md): Renovate proposes them but must never merge
one, and Diun's alerts stay as a second signal. So a pin that Diun doesn't watch, or watches at another tag, would go
quiet, and a Renovate setting that lets an engine merge by itself would restart every app's database unattended.
An engine is a service with the label ``org.honeybeartech.mnemosyne.engine``. Rules:

- ``watched``: diun/images.yml has exactly one entry for the engine's image repository.
- ``pinned-tag``: that entry's name carries the tag compose.yaml pins (so the rebuild of that tag is watched).
- ``watch-repo``: the entry watches the repository's tags (``watch_repo: true``) with ``include_tags``.
- ``include``: one of ``include_tags`` matches the pinned tag (a pattern that doesn't is a typo, and would likely
  miss the next release too).
- ``stale``: no entry watches an image that compose.yaml doesn't pin as an engine.
- ``renovate``: renovate.json keeps the engine from merging by itself, by a strict allow-list (anything unknown
  fails, so a new setting is reviewed on purpose rather than trusted): the last packageRule is the engine's hold
  (only ``description``, ``matchPackageNames``, ``automerge: false`` and ``prBodyNotes``, with the engine named
  exactly); no rule disables something that could include the engine; ``extends`` only lists presets known not to
  turn automerge on; ``vulnerabilityAlerts`` only sets labels; and the engine, its manager and the custom managers
  are not ignored or disabled.
- ``diun-manager``: a custom regex manager in renovate.json reads the engine's tag from its diun/images.yml entry,
  so a version bump changes that file and compose.yaml in one pull request.

Exit codes: 0 = consistent, 1 = problems, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from check_compose import ImageRef, parse_image

# Everything renovate.json may contain that this check can't prove harmless is a problem: review it, then extend
# these lists on purpose.
HOLD_KEYS = {"description", "matchPackageNames", "automerge", "prBodyNotes"}
KNOWN_PRESETS = {
    "config:recommended",
    "docker:pinDigests",
    "helpers:pinGitHubActionDigests",
    ":semanticCommitsDisabled",
}
ALERT_KEYS = {"description", "labels"}
PLAIN_NAME = re.compile(r"[A-Za-z0-9._-]+")  # no glob, regular expression, negation or other special character
PLAIN_PACKAGE = re.compile(r"[A-Za-z0-9._/-]+")  # the same, and a namespace/ (never a leading / or a /regex/)
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


# The packageRule keys that match a package by name (anything else under "match" narrows a rule), and the ones
# that match by regular expression.
def dependency_name(repository: str) -> str:
    """Renovate's name for an image: Docker Hub's official images without docker.io/library/."""
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


def hold_problems(name: str, rules: list[Any]) -> list[str]:
    """Return why the last packageRule isn't the engine's never-merge rule."""
    hold = rules[-1] if rules else None
    names = hold.get("matchPackageNames") if isinstance(hold, dict) else None
    if (
        isinstance(hold, dict)
        and set(hold) <= HOLD_KEYS
        and hold.get("automerge") is False
        and isinstance(names, list)
        and all(isinstance(n, str) and PLAIN_NAME.fullmatch(n) for n in names)
        and name in names
    ):
        return []
    keys = ", ".join(sorted(HOLD_KEYS))
    return [
        (
            f'the last packageRule must be the {name} rule: only the keys {keys}, "automerge": false, and '
            f'"matchPackageNames" a list of plain names (no pattern characters) with "{name}" in it'
        )
    ]


def disabling_problems(name: str, rules: list[Any]) -> list[str]:
    """Return the rules that disable something that could include the engine."""
    problems = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or rule.get("enabled") is not False:
            continue
        names = rule.get("matchPackageNames") or rule.get("matchDepNames")
        datasources = rule.get("matchDatasources")
        plain = (
            isinstance(names, list)
            and all(isinstance(n, str) and PLAIN_PACKAGE.fullmatch(n) for n in names)
            and name.lower() not in {n.lower() for n in names}
        )
        other = isinstance(datasources, list) and bool(datasources) and "docker" not in datasources
        if not (plain or other):
            problems.append(
                f"packageRules[{index}] disables updates and could include {name}: give it plain package names "
                "without it, or a matchDatasources without docker"
            )
    return problems


def settings_problems(name: str, renovate: dict[str, Any]) -> list[str]:
    """Return the top-level settings that could let the engine merge by itself, or stop it being proposed."""
    problems = [
        f"extends has {preset}, which this check doesn't know: review it, then add it to KNOWN_PRESETS"
        for preset in map(str, renovate.get("extends") or [])
        if preset not in KNOWN_PRESETS
    ]
    alerts = renovate.get("vulnerabilityAlerts", {})
    if not isinstance(alerts, dict) or set(alerts) - ALERT_KEYS:
        problems.append("vulnerabilityAlerts may only set labels (no automerge, extends or packageRules)")
    if not isinstance(renovate.get("osvVulnerabilityAlerts", False), bool):
        problems.append("osvVulnerabilityAlerts must be true or false")
    if renovate.get("enabled") is False:
        problems.append("Renovate is disabled (enabled: false)")
    if name in {str(n) for n in renovate.get("ignoreDeps") or []}:
        problems.append(f"ignoreDeps has {name}")
    managers = renovate.get("enabledManagers")
    if managers is not None and not {"docker-compose", "custom.regex"} <= set(managers):
        problems.append("enabledManagers must include docker-compose and custom.regex")
    for key in ("docker-compose", "custom.regex"):
        block = renovate.get(key)
        if isinstance(block, dict) and block.get("enabled") is False:
            problems.append(f'"{key}" is disabled (enabled: false)')
    if any(isinstance(m, dict) and m.get("enabled") is False for m in renovate.get("customManagers") or []):
        problems.append("a customManagers entry is disabled (enabled: false)")
    return problems


def renovate_problems(service: str, name: str, renovate: dict[str, Any]) -> list[str]:
    """Return why Renovate might merge the engine `name` by itself, or not propose it."""
    rules = renovate.get("packageRules")
    rules = rules if isinstance(rules, list) else []
    found = hold_problems(name, rules) + disabling_problems(name, rules) + settings_problems(name, renovate)
    return [f"{service}: [renovate] {problem}" for problem in found]


def diun_manager_problems(service: str, name: str, entry: dict[str, Any], renovate: dict[str, Any]) -> list[str]:
    """Return why no custom regex manager in renovate.json reads the engine's tag from its Diun entry."""
    pin = parse_image(str(entry.get("name", "")))
    line = f"- name: {entry.get('name', '')}"
    for manager in renovate.get("customManagers") or []:
        if not isinstance(manager, dict) or manager.get("customType") != "regex":
            continue
        files = [str(p) for p in manager.get("managerFilePatterns") or []]
        reads_diun = any(re.search(p[1:-1], "diun/images.yml") for p in files if p.startswith("/") and p.endswith("/"))
        if not reads_diun or manager.get("datasourceTemplate") != "docker":
            continue
        for pattern in manager.get("matchStrings") or []:
            match = re.search(re.sub(r"\(\?<([A-Za-z]+)>", r"(?P<\1>", str(pattern)), line + "\n", re.MULTILINE)
            if match and match.groupdict().get("depName") == name and match.groupdict().get("currentValue") == pin.tag:
                return []
    return [
        (
            f"{service}: [diun-manager] renovate.json has no regex manager that reads {name} and its tag from "
            "diun/images.yml (with datasourceTemplate docker)"
        )
    ]


def check_engine(service: str, image: str, watches: list[dict[str, Any]], renovate: dict[str, Any]) -> list[str]:
    """Return the problems with one engine's watch and Renovate rules."""
    pin = parse_image(image)
    name = dependency_name(pin.repository)
    problems = watch_problems(service, pin, watches)
    problems += renovate_problems(service, name, renovate)
    entries = [w for w in watches if parse_image(str(w.get("name", ""))).repository == pin.repository]
    if len(entries) == 1:
        problems += diun_manager_problems(service, name, entries[0], renovate)
    return problems


def check(compose: dict[str, Any], watches: list[dict[str, Any]], renovate: dict[str, Any]) -> list[str]:
    """Every problem, engine by engine, then the stale watches."""
    pinned = engines(compose)
    problems = []
    for service, image in sorted(pinned.items()):
        problems += check_engine(service, image, watches, renovate)
    repositories = {parse_image(image).repository for image in pinned.values()}
    for entry in watches:
        repository = parse_image(str(entry.get("name", ""))).repository
        if repository not in repositories:
            problems.append(
                f"diun/images.yml: [stale] watches {repository}, which compose.yaml doesn't pin as an engine"
            )
    return problems


def load(path: Path) -> Any:  # noqa: ANN401 # documents are whatever the file holds
    """Read a YAML file, or a JSON one (renovate.json)."""
    text = path.read_text(encoding="utf-8")
    return json.loads(text) if path.suffix == ".json" else yaml.safe_load(text)


def main(argv: list[str] | None = None) -> int:
    """Run the check; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the checkout (default: this script's)")
    args = parser.parse_args(argv)
    try:
        compose = load(args.root / "compose.yaml")
        watches = load(args.root / "diun" / "images.yml")
        renovate = load(args.root / "renovate.json")
    except (OSError, ValueError, yaml.YAMLError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    if not isinstance(compose, dict) or not isinstance(watches, list) or not isinstance(renovate, dict):
        print("error: compose.yaml, diun/images.yml or renovate.json isn't what it should be", file=sys.stderr)
        return 2
    problems = check(compose, watches, renovate)
    for problem in problems:
        print(problem)
    print(f"{len(engines(compose))} engine(s) checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
