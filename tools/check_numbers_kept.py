"""Check that a rewrite of the documents kept every number and decision identifier.

For each Markdown document the committed version and the working version are scanned for numeric
tokens and decision identifiers, and the two multisets must be equal. A difference is printed with
its counts so that it can be restored or explained, and the exit status is 1 if any document
differs. Wrapping, headings and wording may change freely.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

NUMBER = re.compile(r"(?<![\w.])[-+]?\d+(?:[.,]\d+)*(?:[eE][-+]?\d+)?")
DECISION = re.compile(r"\b(?:D|P|R|LK-|SG)\d+[a-z]?\b")


def tokens(text: str) -> Counter[str]:
    """Count the numeric tokens and decision identifiers of a text."""
    found = Counter(NUMBER.findall(text))
    found.update(DECISION.findall(text))
    return found


def documents(root: Path) -> list[str]:
    names = ["README.md", "CONTRIBUTING.md"]
    names += sorted(p.relative_to(root).as_posix() for p in (root / "docs").glob("*.md"))
    return names


def differences(before: Counter[str], after: Counter[str]) -> list[str]:
    """Describe the tokens whose counts differ, as removed or added."""
    lines: list[str] = []
    for token in sorted(set(before) | set(after)):
        if before[token] != after[token]:
            lines.append(f"  {token}: {before[token]} -> {after[token]}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="HEAD", help="revision holding the original documents")
    args = parser.parse_args(argv)
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    failed = 0
    for name in documents(root):
        shown = subprocess.run(
            ["git", "show", f"{args.base}:{name}"], cwd=root, capture_output=True, text=True
        )
        if shown.returncode != 0:
            print(f"{name}: new document, nothing to compare")
            continue
        diff = differences(tokens(shown.stdout), tokens((root / name).read_text(encoding="utf-8")))
        print(f"{name}: {'same tokens' if not diff else f'{len(diff)} tokens differ'}")
        for line in diff:
            print(line)
        failed += bool(diff)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
