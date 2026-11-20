# Decisions log

Maintenance decisions, why they were made, and what was considered instead.

## 2026-11-20 - Renovate replaces Dependabot (renovate-migrate, #48)

**Decision.** Renovate (`renovate.json`, at the root as plain JSON so CI's Python can read it) proposes every
dependency update, and `.github/dependabot.yml` is removed. Both tools had been active since Renovate's onboarding
(#26). The config follows homelab-hyperion's. Dependabot security updates were turned off by the owner; Dependabot
alerts stay on.

**Everything except the engines merges by itself**, as under Dependabot: patch, minor and major updates and image
rebuilds, once every required check passes. New: a version waits 3 days after its release, where the registry dates
it. Vulnerability fixes and rebuilds don't wait. The pip-compile lock-file refresh is off, because it would skip the
wait.

**The engines (owner, 2026-11-20).** PostgreSQL and MariaDB are proposed but never merged by Renovate; the owner
merges them at a quiet time, because a new engine version restarts every app's database. A new major version opens a
pull request only once it is ticked on the Dependency Dashboard; a new MariaDB series within the same major arrives as
an ordinary engine pull request. Renovate also moves the engines' tags in `diun/images.yml` (a regex manager), so a
version bump changes both files in one pull request (Renovate groups updates by branch name; checked against Renovate
itself). Diun's alerts stay. This replaces the 2026-10-26 rule that Dependabot ignore the engines.

**The CI check.** `scripts/check_watches.py` now checks `renovate.json`: the last rule must be the engines'
`automerge: false` rule in a fixed form, and presets, vulnerability-alert settings and disabling rules outside a short
allow-list fail CI.

**Alternatives rejected.**
- Ignore the engines, as before: the owner chose to have them proposed.
- `.github/renovate.json5` with comments, as in the other stacks: CI's Python has no JSON5 parser.
- Require release dates for the wait (`timestamp-required`): undated versions would never be proposed.

**Review findings fixed.** The audit found ways to get round the CI check: names in capitals, regex flags, combined
matchers, empty matchers, brace and extglob patterns, a preset in the vulnerability-alert settings, and the
Compose manager switched off. Two fix rounds turned the check into a strict allow-list.

**Open after two fix rounds.** The audit still found settings the check doesn't cover: rules inside a manager's own
block, group settings and `overridePackageName` on an earlier rule, regex or case variants in disabling rules, and
`ignorePaths` or a manager-level `ignoreDeps`. Each needs a deliberate edit of `renovate.json`; the current config
keeps both engines from merging by themselves (confirmed against Renovate), and Renovate never edits that file
(`configMigration` is off by default). The docs now say the check catches mistakes, not every setting, and that a
change to `renovate.json` needs a careful review. A roadmap item covers a complete check.

**Review findings rejected.**
- "Dependabot security updates may still be on": the owner turned them off for every repository before this job.
- "One pull request for both engine files is unverified": the audit confirmed it with Renovate's own lookup.
- "`timestamp-optional` lets undated versions skip the wait": the same in the other stacks, and documented.

**Left as is.** `.github/workflows/dependabot-auto-merge.yml` and the Dependabot comments in `ci.yml` and `scan.yml`
are unchanged (workflow files are outside this job); the workflow only acts on Dependabot's pull requests.
