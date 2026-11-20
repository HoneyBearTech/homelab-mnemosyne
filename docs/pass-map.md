# Pass map

A short record of each piece of maintenance work: when it happened, what shipped, and where.

| Date | Job | What shipped | PR |
| --- | --- | --- | --- |
| 2026-11-20 | renovate-migrate | Dependency updates moved from Dependabot to Renovate (`renovate.json` replaced; `.github/dependabot.yml` removed). Everything except the engines merges by itself after the required checks, with a 3-day wait for dated releases. PostgreSQL and MariaDB are proposed but never merged by Renovate; their majors wait for Dependency Dashboard approval; Renovate moves their tags in `diun/images.yml` in the same pull request. `scripts/check_watches.py` checks `renovate.json` instead of the Dependabot file. `requirements-dev.txt` re-locked (same versions). Docs updated. | [#48](https://github.com/HoneyBearTech/homelab-mnemosyne/pull/48) |
