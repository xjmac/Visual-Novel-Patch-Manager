#!/usr/bin/env python3
"""Fail if personal data that was stripped from history is about to return.

Usage: check_privacy.py            # scan all tracked files (CI)
       check_privacy.py --staged   # scan staged files (pre-commit hook)
"""
import re
import subprocess
import sys
from pathlib import PurePosixPath

# Filenames removed from history with git filter-repo (personal Steam dumps)
# and local-only notes. Matched by basename anywhere in the tree.
FORBIDDEN_NAMES = {
    "raw_licenses.txt",
    "my_steam_games.txt",
    "ROADMAP.md",
    "AGENTS.md",
    "CODEBASE_REPORT.md",
    ".grokignore",
    ".env",
}
FORBIDDEN_GLOBS = ("*.dump", "*licenses*dump*", "*steam*games*.txt")

# Real home directories. Generic placeholders used by tests/docs stay allowed.
ALLOWED_HOMES = {"deck", "user", "runner", "username", "you", "example", "test", "<user>"}
HOME_RE = re.compile(r"(?:/home/|/Users/|C:\\\\?Users\\\\?)([A-Za-z0-9_.-]+)")
# Steam account data (userdata/<steamid>) and license-dump signatures.
CONTENT_RES = [
    (re.compile(r"userdata[/\\][0-9]{5,}"), "Steam userdata/<account id> path"),
    (re.compile(r"Payment Method|Purchase Date|Acquisition Method"), "Steam license dump text"),
]


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout


def main():
    staged = "--staged" in sys.argv
    if staged:
        files = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    else:
        files = git("ls-files", "-z")
    problems = []
    for name in filter(None, files.decode().split("\0")):
        p = PurePosixPath(name)
        if p.name in FORBIDDEN_NAMES or any(p.match(g) for g in FORBIDDEN_GLOBS):
            problems.append(f"{name}: forbidden personal/local file")
            continue
        if p.name == "check_privacy.py":
            continue
        try:
            data = git("show", f":{name}") if staged else open(name, "rb").read()
        except (OSError, subprocess.CalledProcessError):
            continue
        if b"\0" in data[:8192]:
            continue
        text = data.decode("utf-8", "replace")
        for n, line in enumerate(text.splitlines(), 1):
            for m in HOME_RE.finditer(line):
                if m.group(1).lower() not in ALLOWED_HOMES:
                    problems.append(f"{name}:{n}: real home path {m.group(0)!r}")
            for rx, why in CONTENT_RES:
                if rx.search(line):
                    problems.append(f"{name}:{n}: {why}")
    if problems:
        print("Privacy check failed (see PRIVACY.md):", file=sys.stderr)
        print("\n".join("  " + x for x in problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
