# Contributing to homelab-mnemosyne

homelab-mnemosyne is a personal project with a single maintainer (see [GOVERNANCE.md](GOVERNANCE.md)). It
describes one server, so most changes are the maintainer's own, but issues and pull requests are welcome.
There is no service-level agreement, and review may take a while. Releases are tagged
`vMAJOR.MINOR.PATCH`; only the latest release and `main` are supported ([SUPPORT.md](SUPPORT.md)). Everyone
taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting bugs and suggesting changes

- Use [GitHub Issues](https://github.com/HoneyBearTech/homelab-mnemosyne/issues) for bugs, questions and ideas.
  Say which version you run, which service is involved and what you ran, and leave out passwords, tokens, hostnames,
  addresses and paths. For anything bigger than a small fix, please open an issue first so we can agree on
  the approach. The [roadmap](docs/roadmap.md) says what's planned and what's out of scope.
- A bug in a service itself (PostgreSQL, MariaDB, an exporter, Diun) belongs with that project.
- **Do not report security vulnerabilities in a public issue.** Follow [SECURITY.md](SECURITY.md) and use
  GitHub's private vulnerability reporting instead.

## Development setup

You need git, Python 3.14, and Docker with Compose v2.

```sh
git clone https://github.com/HoneyBearTech/homelab-mnemosyne.git && cd homelab-mnemosyne
make test     # creates .venv with the hash-pinned tools, runs the checkers' and scripts' tests with coverage
make lint     # ruff, ruff format, yamllint, shellcheck
cp .env.example .env && make check   # the policy check over the resolved Compose file, and the engines' watches
make smoke    # starts the whole stack with throwaway settings and secrets, waits until every service is healthy,
              # then creates logins and databases, checks who can reach what, dumps, changes and restores
```

How the stack fits together is in [docs/architecture.md](docs/architecture.md).

## When and how tests run

Every push and pull request runs two CI jobs ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)), both
required checks on `main`. "Checks + tests" runs the linters below, a gitleaks scan of the whole history,
the unit tests with a coverage floor, `docker compose config`, the policy check
([`scripts/check_compose.py`](scripts/check_compose.py)) and the watch check
([`scripts/check_watches.py`](scripts/check_watches.py)). "Stack smoke test"
([`scripts/smoke-test.sh`](scripts/smoke-test.sh)), on an amd64 runner like the server, pulls the pinned
images (logged in to Docker Hub with the project's read-only token when it's set, and logged out again before
anything starts), creates throwaway secrets and folders under a throwaway `CONFIG_ROOT` (`scripts/db.sh init`),
fails unless every service reports healthy within five minutes, then creates app logins and databases on both
engines and checks that each app reaches its own databases over the network (PostgreSQL over TLS) and no other
app's, that neither superuser can log in over the network, that both exporters are logged in, that a password
change takes effect, and that a dump of everything restores one database at a time, with its access rules. CodeQL, dependency
review, a DCO check and OpenSSF Scorecard also run on the repository.

The maintainer also keeps a copy on a self-hosted GitLab, mirrored from GitHub by a scheduled job in
[`.gitlab-ci.yml`](.gitlab-ci.yml), which re-runs the "Checks + tests" steps that need no Docker daemon on
every commit it receives. Changes go to GitHub only; a commit made on the GitLab copy stops the mirror. (The
GitLab project, its `MIRROR_TOKEN` variable and the schedule aren't set up yet; until they are, the file does
nothing.)

The unit tests are offline: the checkers get fixtures (the policy checker's JSON in
[`tests/fixtures/`](tests/fixtures/)), and the scripts are run only up to their argument and safety checks, with
a stand-in `docker` that fails the test if it's ever called. The smoke test needs both: it pulls the pinned images.

## Before you open a pull request

Run what CI runs and make sure it passes:

```sh
make lint
make test
make check
make smoke    # when the pull request changes compose.yaml
```

The workflow and secret scanners run in containers; the exact commands are in
[`ci.yml`](.github/workflows/ci.yml).

## Coding standards

- **Compose** (`compose.yaml`): every image pinned as `name:tag@sha256:<digest>` (Dependabot updates both);
  settings from `.env` through `${VAR}`; no `privileged`, added capabilities, host network or PID namespace,
  or Docker socket mount unless the service has an `org.honeybeartech.mnemosyne.allow.<rule>` label giving the
  reason; every service has a health check. `scripts/check_compose.py` enforces this.
- **Python** (`scripts/`, `tests/`): [PEP 8](https://peps.python.org/pep-0008/) and
  [PEP 257](https://peps.python.org/pep-0257/), enforced by [ruff](https://docs.astral.sh/ruff/) with every rule
  family enabled, including type annotations, docstrings and the bandit security rules, and `ruff format`; the
  few rules left out, and why, are in [`pyproject.toml`](pyproject.toml). Standard library only.
- **YAML** (compose file, workflows, templates): [yamllint](https://yamllint.readthedocs.io/) with
  [`.yamllint.yml`](.yamllint.yml), warnings treated as errors.
- **Shell scripts** (`scripts/*.sh`): bash with `set -euo pipefail`, checked by
  [shellcheck](https://www.shellcheck.net/).
- **GitHub Actions workflows**: [actionlint](https://github.com/rhysd/actionlint), which also runs
  [shellcheck](https://www.shellcheck.net/) on every `run:` script. Actions are pinned by commit SHA, jobs
  ask for the fewest permissions they need, and untrusted values reach scripts through `env:`, never
  `${{ }}` inside `run:`.
- Exceptions are made per line (for example `# noqa: S603 - reason`) with the reason next to them, never by
  turning a rule off for the whole repository.

## Test policy

- **New checker rules come with tests**: a fixture case that triggers the rule and one that must not;
  `test_every_rule_is_reported_exactly` stays exact, so a new false positive fails it.
- **Bug fixes come with a regression test** that fails before the fix, where the bug can be tested at all.
- Unit tests must keep statement and branch coverage of `scripts/` at or above the floor in
  `pyproject.toml` (90 %); CI fails below it.
- A change to `compose.yaml` is tested by the policy check and the smoke test in CI, and by
  `docker compose up -d` on a host before it is released; the pull request says how it was tried.

## Developer Certificate of Origin

Every commit must be signed off to certify the [Developer Certificate of Origin](https://developercertificate.org/):
that you wrote the change or otherwise have the right to submit it under the project's license. Add the
sign-off with `git commit -s`, which appends:

```
Signed-off-by: Your Name <you@example.com>
```

using your git `user.name` and `user.email`. The DCO check
([`.github/workflows/dco.yml`](.github/workflows/dco.yml)) fails a pull request with an unsigned commit; fix
it with `git rebase --signoff main` and force-push your branch.

## Pull requests

- `main` is protected: changes land only through a pull request, and the required CI check must pass. Pull
  requests are squash-merged.
- Keep each pull request focused on one change, and describe what it does and why. An image bump links the
  service's release notes and says whether it migrates the service's data.
- Update `README.md`, `.env.example`, the docs and `CHANGELOG.md` (under "Unreleased") when you change
  settings, services or user-visible behaviour.
- **This repository is public.** Never commit passwords, tokens, certificates, `.env` files, hostnames, domains, IP
  addresses or host paths. Secret scanning with push protection is on, and CI runs gitleaks over the
  history.

## Releases

The maintainer adds a `## [x.y.z] - date` section to `CHANGELOG.md`, then pushes a signed tag
(`git tag -s vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`). The release workflow checks the policy, signs
the checksums and creates the GitHub Release from that changelog section
([docs/verifying-releases.md](docs/verifying-releases.md)).

## License

By contributing, you agree that your contribution is licensed under the project's [MIT License](LICENSE).
