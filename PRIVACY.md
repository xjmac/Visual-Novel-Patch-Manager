# Privacy

History was rewritten with `git filter-repo` to remove a personal Steam
license dump and owned-games list (`scripts/raw_licenses.txt`,
`scripts/my_steam_games.txt`). These must never return. The converters take a
path you supply; do not commit the files they read.

Also kept out: local notes (`ROADMAP.md`, `AGENTS.md`, `CODEBASE_REPORT.md`,
`.grokignore`), `.env`, `*.dump`, real home paths (`/home/<name>`,
`/Users/<name>`; `/home/deck` is fine), and Steam `userdata/<account id>` paths.
Commits use the GitHub noreply author address.

Grok Build sessions load `.grok/rules/privacy.md`, which forbids real game
titles, IDs and paths. `scripts/check_privacy.py` enforces this in CI. Enable the local hook with:

    git config core.hooksPath .githooks
