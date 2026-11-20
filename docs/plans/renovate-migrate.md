# Plan: move dependency updates from Dependabot to Renovate

**What the owner asked for:** "remove Dependabot workflows, turn off Dependabot security updates, and turn on Renovate."
For the two database engines, the owner chose (2026-11-20): Renovate proposes them, but they never merge by
themselves.

## What we found

- Both tools are active: Dependabot (`.github/dependabot.yml`) and Renovate, whose `renovate.json` (added in #26) is
  the bare recommended preset. Renovate already proposes engine updates (#30 and #32 were merged by hand, #44 is open)
  and opens duplicates of Dependabot's.
- Dependabot ignores postgres and mariadb (owner, 2026-10-26); Diun alerts on them instead. `scripts/check_watches.py`
  fails CI if an engine isn't ignored in `.github/dependabot.yml`, so it must read Renovate's config instead.
- An engine version bump must also change the tag in `diun/images.yml`, or that same check fails.
- Renovate can't read `requirements-dev.txt` as it is (a one-line header instead of pip-compile's own, and 119
  repeated hashes), the same problem homelab-hyperion had.
- The required checks and `dco.yml` already accept Renovate's commits.

## What we'll change

1. **Re-lock `requirements-dev.txt`** with pip-compile on Python 3.14, keeping every version.
   *Check:* same versions; CI's checks and tests pass; Renovate's dry run reads all 11 packages.
2. **Replace `renovate.json`** (it stays at the root, plain JSON, so CI's Python can read it without a new
   dependency; each rule explains itself in a `description`). It follows homelab-hyperion's config: Mondays from
   06:00 UTC, assigned to the owner, images and Actions pinned by digest or SHA, signed and signed-off commits.
   - **Everything except the engines merges by itself** once every required check passes, as today: patch, minor
     and major updates and image rebuilds. New versions wait 3 days first, where the registry dates them; security
     fixes and rebuilds don't wait. Renovate's periodic whole-lock-file refresh is off, so it can't skip the wait.
   - **The engines (postgres, mariadb) are proposed but never merge by themselves.** Rebuilds and minor or patch
     versions open a pull request for the owner to merge at a quiet time. A new major version (or series) only opens
     one once the owner ticks it on the Dependency Dashboard, since it needs a planned upgrade (`docs/upgrading.md`).
   - **Renovate also updates the engine tags in `diun/images.yml`**, so a version bump changes both files in one
     pull request and the watch check keeps passing. Diun's alerts stay.
   - Also: CodeQL's actions move together; Python's minor version, the runner label and the idle auto-merge
     workflow's own action stay hand-picked; images in workflow `docker run` lines and `.gitlab-ci.yml` are now
     proposed too.
   *Check:* the config validator in strict mode; a dry run that finds every pinned file, including `diun/images.yml`.
3. **`scripts/check_watches.py`:** its `dependabot` rule becomes a `renovate` rule. CI fails if an engine could
   merge by itself (no never-merge rule for it, a later rule that could turn merging back on, or the engine left out
   of Renovate). Tests in `tests/test_check_watches.py` cover each case.
   *Check:* `make test` and `make lint`; the check passes on the repo itself.
4. **Delete `.github/dependabot.yml`.** Its explanation of the engine rule moves into `docs/upgrading.md`.
5. **Update the docs and comments that name Dependabot**: `docs/dependencies.md`, `docs/upgrading.md`,
   `GOVERNANCE.md`, `README.md`, `CONTRIBUTING.md`, `SUPPORT.md`, `docs/architecture.md`, `docs/interfaces.md`,
   `docs/security.md`, `docs/assurance-case.md`, comments in `compose.yaml`, `diun/images.yml`, `.gitlab-ci.yml` and
   the `Makefile`, and a `CHANGELOG.md` entry.
6. **Job notes:** `docs/roadmap.md`, and new `docs/pass-map.md` and `docs/decisions-log.md`.

Nothing in `.github/workflows` changes; `dependabot-auto-merge.yml` stays, and nothing triggers it any more.

## Who's on it

Researcher (done), Engineer, QA, Security Officer, Auditor.

## Risks

- A merge deploys. Non-engine updates already merge unattended; the 3-day wait makes that slightly safer.
- Open Renovate pull requests #43 and #46 edit `requirements-dev.txt` the old way; Renovate will close and redo them
  after this merges. #44 (a mariadb rebuild) stays open for the owner.
- Renovate's pull requests run CI with the Docker Hub secret, as in the other stacks; CI logs out before any
  container under test starts.

## Out of scope

- Deleting `dependabot-auto-merge.yml` and the workflow comments that name Dependabot (workflow files).
- Repo settings and secrets.
