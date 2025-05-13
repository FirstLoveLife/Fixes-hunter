#!/usr/bin/env python3
"""
find_fixes_grep.py  –  parallel, recursive, real‑time

Scan a Linux git tree for commits that fix the subjects listed in <file>.
Optionally (default) follow the trail further: if commit X fixes subject A,
search for commits that later fix X itself, and so on.

Key features
------------
• Parallel   : one worker per CPU (override with -j)  
• Real‑time  : results are printed as soon as they are found  
• Recursive  : enabled by default; disable with --no-recursive  
• Time window: last 10 years by default; change with --since  
• Branch filter, case‑insensitive matching, verbose diagnostics

The file passed as <subjects> **must contain one commit subject per line – no hashes**.

Author: Li Chen <me@linux.beauty>
"""

from __future__ import annotations
import argparse, concurrent.futures as cf, os, pathlib, re, shlex, subprocess, sys

# ---------- CLI --------------------------------------------------------------
cli = argparse.ArgumentParser(description="Find commits that Fix <subject> (parallel, recursive)")
cli.add_argument("subjects", help="file: one commit subject per line")
cli.add_argument("repo",     help="path to Linux git repository")
cli.add_argument("-b", "--branch", action="append",
                 help="branch/ref to search (repeatable); default = --all")
cli.add_argument("-s", "--since", default="10 years ago",
                 help='git log --since (default: "10 years ago")')
cli.add_argument("-i", "--ignore-case", action="store_true",
                 help="case‑insensitive grep")
cli.add_argument("-j", "--jobs", type=int, default=os.cpu_count(),
                 help="concurrent workers (default: CPU count)")
cli.add_argument("--no-recursive", action="store_true",
                 help="do NOT follow secondary Fixes chains")
cli.add_argument("-v", "--verbose", action="store_true",
                 help="verbose: print git commands and progress")
args = cli.parse_args()

# ---------- helpers ----------------------------------------------------------
REPO = pathlib.Path(args.repo).expanduser()
GIT  = ["git", "-C", str(REPO)]
BRANCHES = args.branch or ["--all"]
SINCE   = f"--since={args.since}"
ICASE   = ["-i"] if args.ignore_case else []
VISITED: set[str] = set()       # avoid printing the same hash twice (any depth)

def run(cmd: list[str]) -> str:
    """Run git command and return stdout."""
    if args.verbose:
        print("+", " ".join(shlex.quote(c) for c in cmd), file=sys.stderr, flush=True)
    return subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")

def grep_fixes(regex: str) -> list[tuple[str, str]]:
    """Return [(hash, title), ...] for commits whose Fixes: line matches regex."""
    cmd = GIT + ["log", *BRANCHES, SINCE, *ICASE,
                 "--grep=" + regex, "--extended-regexp",
                 "--pretty=%H%x1f%s"]
    out = run(cmd).strip()
    pairs = []
    for line in out.splitlines():
        if "\x1f" in line:
            h, t = line.split("\x1f", 1)
            pairs.append((h, t))
    return pairs

def follow_chain(hash_to_fix: str, indent: int) -> None:
    """Recursively search for commits that fix *hash_to_fix* itself."""
    regex = rf"^Fixes:\s*{hash_to_fix[:12]}"          # first 12 chars are unique
    for h, title in grep_fixes(regex):
        if h in VISITED:
            continue
        VISITED.add(h)
        print(" " * indent + f"↳ fixed by {h} : {title}", flush=True)
        if not args.no_recursive:
            follow_chain(h, indent + 2)

def process_subject(subject: str) -> None:
    """Search primary Fixes lines for *subject* and output chains."""
    if args.verbose:
        print(f"# searching: {subject}", file=sys.stderr, flush=True)

    # Escape special chars in subject for regex
    pattern = rf"^Fixes:.*{re.escape(subject)}.*"
    for h, title in grep_fixes(pattern):
        if h in VISITED:
            continue
        VISITED.add(h)
        # Primary match: print subject first, then its fixer
        print(f"{subject}\n↳ fixed by {h} : {title}", flush=True)
        if not args.no_recursive:
            follow_chain(h, 2)

# ---------- load subject list -----------------------------------------------
sub_file = pathlib.Path(args.subjects).expanduser()
subjects = [ln.rstrip("\n") for ln in sub_file.open(encoding="utf-8") if ln.strip()]
if not subjects:
    sys.exit("subject list is empty")

# ---------- parallel execution ----------------------------------------------
with cf.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
    fut2sub = {pool.submit(process_subject, s): s for s in subjects}
    for fut in cf.as_completed(fut2sub):
        try:
            fut.result()
        except Exception as exc:
            print(f"# error while processing '{fut2sub[fut]}': {exc}",
                  file=sys.stderr, flush=True)

