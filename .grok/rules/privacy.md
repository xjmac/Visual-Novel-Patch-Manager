# Privacy rule (standing, all sessions)

This repo is public. History was rewritten to strip personal data; do not re-add it.

- In code, tests, fixtures, docs, comments, and commit messages, use only
  synthetic placeholder game titles (e.g. "Example Visual Novel"), fake app ids,
  and placeholder paths (`/home/deck/...`, `/home/user/...`, `tmp_path`).
- Never commit or mention: real game titles from the developer's Steam library
  or local install, real install paths under the developer's home directory,
  real Steam IDs / account ids / `userdata/<id>` paths, license or library dumps,
  personal emails or names (including the owner's real name; use `xjmac`),
  or any other personal identifier.
- If a real local file or scan result inspires a test, rewrite it with invented
  values before it reaches the repo. Do not copy real data from the machine.
- Git author is always `xjmac <317002279+xjmac@users.noreply.github.com>`.
- `scripts/check_privacy.py` (CI + `.githooks/pre-commit`) enforces the
  path/dump rules; game-title privacy is on you. See `PRIVACY.md`.
