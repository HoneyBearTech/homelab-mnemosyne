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
- ``renovate``: renovate.json names the engine in a packageRule with ``automerge: false`` and no other matcher, no
  later rule could turn automerge back on for it, no ``extends`` preset turns automerge on, and Renovate isn't told
  to ignore or disable the engine.
- ``diun-manager``: a custom regex manager in renovate.json reads the engine's tag from its diun/images.yml entry,
  so a version bump changes that file and compose.yaml in one pull request.

Exit codes: 0 = consistent, 1 = problems, 2 = unreadable input.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from check_compose import ImageRef, parse_image

MIN_REGEX_LENGTH = 3  # "/x/": a /regular expression/ name has at least one character between the slashes
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
NAME_KEYS = ("matchPackageNames", "matchDepNames")
PATTERN_KEYS = ("matchPackagePatterns", "matchDepPatterns")


def name_matches(pattern: str, name: str) -> bool:
    """Renovate's name matching: a /regular expression/ with optional flags, else a case-insensitive glob.

    Fails closed: a regular expression that doesn't compile counts as matching.
    """
    regex = re.fullmatch(r"/(.+)/([a-z]*)", pattern)
    if regex:
        try:
            return re.search(regex[1], name, re.IGNORECASE if "i" in regex[2] else 0) is not None
        except re.error:
            return True
    return fnmatch.fnmatchcase(name.lower(), pattern.lower())


def rule_names(rule: dict[str, Any], keys: tuple[str, ...] = NAME_KEYS) -> list[str]:
    """Return the names a packageRule lists under the given keys."""
    return [str(name) for key in keys for name in rule.get(key) or []]


def could_match(rule: dict[str, Any], name: str) -> bool:
    """Whether a rule might apply to `name`.

    Renovate applies a rule only if every matcher it has matches, so one name matcher that provably excludes the
    engine is enough. A negation counts as matching, and so does a rule with no name matcher.
    """
    for key in (*NAME_KEYS, *PATTERN_KEYS):
        entries = [str(n) for n in rule.get(key) or []]
        if not entries:
            continue
        if key in PATTERN_KEYS:
            entries = [f"/{n}/i" for n in entries]
        if not any(n.startswith("!") or name_matches(n, name) for n in entries):
            return False
    return True


def is_hold(rule: dict[str, Any], name: str) -> bool:
    """Whether a rule covers the engine, sets automerge: false, and has no matcher that narrows it.

    Renovate applies a rule only if every matcher matches: each name matcher the rule has must list the engine,
    and the rule must have no other matcher, negation or pattern.
    """
    populated = [key for key in NAME_KEYS if rule.get(key)]
    narrowed = any(key.startswith("match") and key not in NAME_KEYS and rule[key] for key in rule)
    covers = bool(populated) and all(
        any(not str(n).startswith("!") and name_matches(str(n), name) for n in rule[key]) for key in populated
    )
    negated = any(str(n).startswith("!") for n in rule_names(rule))
    return (
        covers and rule.get("automerge") is False and not narrowed and not negated and rule.get("enabled") is not False
    )


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


def renovate_problems(service: str, name: str, renovate: dict[str, Any]) -> list[str]:
    """Return why Renovate might merge the engine `name` by itself, or not propose it."""
    rules = [r for r in renovate.get("packageRules") or [] if isinstance(r, dict)]
    holds = [i for i, rule in enumerate(rules) if is_hold(rule, name)]
    problems = []
    if not holds:
        problems.append(
            f"{service}: [renovate] renovate.json has no packageRule that names {name} and sets automerge: false "
            "with no other matcher (such as matchUpdateTypes)"
        )
    else:
        problems += [
            f"{service}: [renovate] packageRules[{i}] comes after the {name} rule and could turn automerge back on"
            for i in range(holds[-1] + 1, len(rules))
            if rules[i].get("automerge") is True and could_match(rules[i], name)
        ]
    problems += [
        f"{service}: [renovate] the extends preset {preset} turns automerge on"
        for preset in map(str, renovate.get("extends") or [])
        if "automerge" in preset.lower() and "disable" not in preset.lower()
    ]
    alerts = renovate.get("vulnerabilityAlerts")
    if isinstance(alerts, dict) and alerts.get("automerge") is True:
        problems.append(
            f"{service}: [renovate] vulnerabilityAlerts sets automerge: true, which overrides the {name} rule"
        )
    managers = renovate.get("enabledManagers")
    ignored = (
        name in {str(n) for n in renovate.get("ignoreDeps") or []}
        or renovate.get("enabled") is False
        or any(r.get("enabled") is False and name in rule_names(r) for r in rules)
        or (managers is not None and not {"docker-compose", "custom.regex"} <= set(managers))
    )
    if ignored:
        problems.append(f"{service}: [renovate] renovate.json tells Renovate to ignore or disable {name}")
    return problems


def diun_manager_problems(service: str, name: str, entry: dict[str, Any], renovate: dict[str, Any]) -> list[str]:
    """Return why no custom regex manager in renovate.json reads the engine's tag from its Diun entry."""
    pin = parse_image(str(entry.get("name", "")))
    line = f"- name: {entry.get('name', '')}"
    for manager in renovate.get("customManagers") or []:
        if not isinstance(manager, dict) or manager.get("customType") != "regex":
            continue
        files = [str(p) for p in manager.get("managerFilePatterns") or []]
        if not any(name_matches(p, "diun/images.yml") for p in files) or manager.get("datasourceTemplate") != "docker":
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
