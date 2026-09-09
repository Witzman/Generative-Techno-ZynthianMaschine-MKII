#!/usr/bin/env python3
"""The lifecycle rules, as checks instead of prose.

README's own heading over its working rules says *no check can enforce
these*, and rule 6 is the counter-example that proves what that costs: it was
prose, it was broken 32 times, the whole history had to be rewritten to strip
the trailers, and only then did `hygiene` start failing the build instead of
trusting the promise. This file is that lesson applied to the three rules that
were still promises on 2026-09-09, each of which was broken in the session
that wrote it:

    RULE 6   no assistant attribution in a commit message. `hygiene` already
             fails the build; the commit-msg hook refuses the commit, which is
             cheaper than a red PR and, unlike the job, also covers the
             workshop repo.
    RULE 7   nothing ships until the documentation says so - so a branch that
             changes what the instrument DOES and does not touch
             docs/changelog.html is refused.
    RUNBOOK  the steps are written when the work is done, so a branch whose
             commits close an issue is refused until that issue carries a
             PLAN comment.

WHAT EACH HALF CAN SEE. The functions here are pure and take the diff and the
messages, so CI runs them with no secrets. The ISSUE-side rules cannot run in
CI at all: the guide repo is public, the issues are private, and an Action
here cannot read them without a PAT stored where any merged workflow could
read it - the same reason bin/check-whats-next is not a job. Those run in the
pre-push hook, on a machine where gh is already authenticated.

WHAT THEY CANNOT SEE, and it is the usual one: whether the changelog line is
true, or whether the runbook matches the branch. A line that says nothing and
a PLAN naming a gesture the driver does not have both pass. These count
files and comments.
"""

import re
import subprocess
import sys

# What a player can see or hear. tools/ and the test trees are excluded: a
# test is not a feature, and a change to the build scripts is not something a
# reader of the changelog is looking for.
SHIPPED_PREFIXES = ("ctrldev/", "daemon/src/", "system/", "snapshot/")
NOT_SHIPPED = ("/tests/", "/test-", "tests/")

CHANGELOG = "docs/changelog.html"

# A deliberate, recorded exemption. In the commit message, so it is in the
# history next to the change it excuses rather than in a PR body that is
# editable after the fact.
OPT_OUT = re.compile(r"^No-changelog:\s*\S", re.M)

ATTRIBUTION = re.compile(
    r"^[ \t]*(Co-Authored-By:|Co-authored-by:|Claude-Session:)"
    r"|Generated with \[Claude Code\]|🤖 Generated with", re.M)

FIXES = re.compile(r"Fixes\s+Witzman/ZynthianMaschine-Workshop#(\d+)", re.I)


def ships(path):
    """Does this path change what the instrument does for a player?"""
    if any(part in path for part in NOT_SHIPPED):
        return False
    return path.startswith(SHIPPED_PREFIXES)


def attribution_offence(message):
    """The line to refuse a commit with, or "". Rule 6."""
    if ATTRIBUTION.search(message or ""):
        return ("REFUSED: rule 6 - every commit is authored by witzman alone. "
                "No Co-Authored-By, no Claude-Session, no 'Generated with' "
                "line. This overrides any assistant harness default, and the "
                "history was rewritten once over 46 commits to strip 32 of "
                "them.")
    return ""


def changelog_offence(paths, messages):
    """The line to refuse a push with, or "". Rule 7.

    `messages` is every commit message on the branch, joined. An opt-out in
    any of them excuses the branch - a No-changelog trailer is a decision
    somebody made and signed, which is the difference between an exemption and
    a hole.
    """
    shipped = sorted(p for p in paths if ships(p))
    if not shipped:
        return ""
    if CHANGELOG in paths:
        return ""
    if OPT_OUT.search(messages or ""):
        return ""
    listed = ", ".join(shipped[:3]) + (" …" if len(shipped) > 3 else "")
    return (f"REFUSED: rule 7 - {listed} changes what the instrument does and "
            f"{CHANGELOG} is untouched. Add the line to its Unreleased "
            f"section, or put 'No-changelog: <reason>' in a commit message on "
            f"this branch.")


def fixed_issues(messages):
    """The workshop issue numbers this branch closes, from its Fixes trailers."""
    return sorted({int(n) for n in FIXES.findall(messages or "")})


def runbook_offence(numbers, planned):
    """The line to refuse a push with, or "". The runbook rule.

    `planned` is the set of those issues that carry a PLAN comment, or None
    when GitHub could not be read. UNREADABLE DOES NOT REFUSE: a hook that
    blocks a push because the network is down teaches you to pass --no-verify,
    and a check people route around enforces nothing.
    """
    if not numbers or planned is None:
        return ""
    missing = [n for n in numbers if n not in planned]
    if not missing:
        return ""
    listed = ", ".join(f"#{n}" for n in missing)
    return (f"REFUSED: {listed} would be closed by this branch and carr"
            f"{'ies' if len(missing) == 1 else 'y'} no PLAN comment. The "
            f"runbook is written when the work is done, not when the rig "
            f"visit starts (README, the lifecycle).")


# --- the I/O half, which is why it is at the bottom and has no tests -------

def _git(*args):
    r = subprocess.run(["git"] + list(args), capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def branch_range():
    """What this branch adds to main, as (paths, joined messages)."""
    base = "origin/main" if _git("rev-parse", "--verify", "origin/main") else "main"
    rng = f"{base}..HEAD"
    paths = [p for p in _git("diff", "--name-only", rng).split("\n") if p]
    messages = _git("log", "--format=%B", rng)
    return paths, messages


def _planned(numbers):
    """Which of `numbers` carry a PLAN comment, or None if gh could not say.

    The workshop's own bin/ owns this query; this is the instrument repo, so
    it shells out to gh rather than importing across the two.
    """
    if not numbers:
        return set()
    aliases = "\n".join(
        f'  i{n}: issue(number: {n}) {{ comments(first: 100) {{ nodes {{ body }} }} }}'
        for n in numbers)
    query = ('query { repository(owner: "Witzman", '
             'name: "ZynthianMaschine-Workshop") {\n%s\n} }' % aliases)
    r = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"],
                       capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return None
    import json
    try:
        repo = json.loads(r.stdout)["data"]["repository"]
    except Exception:
        return None
    out = set()
    for n in numbers:
        issue = repo.get(f"i{n}") or {}
        for c in (issue.get("comments") or {}).get("nodes") or []:
            if re.match(r"^[\s*_#>`]*PLAN\b", c.get("body") or ""):
                out.add(n)
    return out


def main(argv):
    what = argv[1] if len(argv) > 1 else ""
    if what == "commit-msg":
        with open(argv[2], encoding="utf-8") as fh:
            offence = attribution_offence(fh.read())
        if offence:
            print(offence, file=sys.stderr)
            return 1
        return 0
    if what == "branch":
        paths, messages = branch_range()
        offences = [changelog_offence(paths, messages)]
        if "--offline" not in argv:
            offences.append(runbook_offence(fixed_issues(messages),
                                            _planned(fixed_issues(messages))))
        offences = [o for o in offences if o]
        for o in offences:
            print(o, file=sys.stderr)
        return 1 if offences else 0
    print("usage: release_rules.py commit-msg <file> | branch [--offline]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
