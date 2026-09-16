#!/usr/bin/env python3
"""Print the .N suffix for a package's disttag, or nothing.

Our disttag follows AlmaLinux: Fedora's release and dist, then .bfin, then a
counter when we rebuild the same Fedora build more than once -- their dnf is
4.14.0-34.el9_8.alma.1 against Red Hat's 34.el9_8, and both .alma and .alma.N
appear in their repositories.

The counter is per package, so it lives beside the package's source entry:

    "dist_bump": {"count": 1, "baseline": "3"}

`baseline` is the spec's own `Release:` that the count was taken against, and
it is what stops the counter outliving its reason. The counter exists only for
the case where the Fedora release we derive from has *not* moved but our build
of it has to. The moment that release moves, the counter is spent: the new
leading segment already outranks everything published against the old one, and
carrying `.1` forward would claim a rebuild that never happened.

Ported from Hummingbird's `bump_release()`, which draws the same distinction
between "Fedora shipped 3.1" and "we already rebuilt Fedora's 3":

    current 3,   baseline 3    -> 3.1
    current 3.1, baseline 3.1  -> 3.1.1
    current 3.1, baseline 3    -> 3.2

We express the counter in the disttag rather than in `Release:`, so the
translation is that a moved baseline retires the counter instead of re-seating
it.

When `Release:` uses macros like `%autorelease`, spec-defined `%global`/`%define`
macros (such as `baserelease`), or conditional release tags, they are evaluated
or queried via `rpmspec` if available, so that `baseline` can be compared
reliably. If an unresolvable macro remains, this refuses to guess and asks for
the bump to be handled by hand.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.package_inventory import source_locks

ROOT = Path(__file__).resolve().parent.parent
RELEASE = re.compile(r"^Release:\s*(.+)$", re.MULTILINE)


class BumpError(Exception):
    """The recorded bump cannot be applied to this spec."""


def _strip_conditional_macros(text: str) -> str:
    """Strip nested RPM conditional macro expressions like %{?...}."""
    while "%{?" in text:
        start = text.find("%{?")
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i : i + 2] == "%{" or text[i : i + 3] == "%{?":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            text = text[:start] + text[end + 1 :]
        else:
            break
    return text


def spec_release(spec: str, spec_path: Path | str | None = None) -> str:
    """The `Release:` value, with macros expanded and trailing dist removed."""
    if spec_path is not None and shutil.which("rpmspec"):
        try:
            out = subprocess.check_output(
                ["rpmspec", "-q", "--srpm", "--qf", "%{RELEASE}", str(spec_path)],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            for dist in ("%{?dist}", "%{dist}"):
                if out.endswith(dist):
                    out = out[: -len(dist)]
                    break
            if out and "%" not in out:
                return out
        except Exception:
            pass

    match = RELEASE.search(spec)
    if match is None:
        raise BumpError("spec has no Release: line")
    release = match.group(1).strip()
    for dist in ("%{?dist}", "%{dist}"):
        if release.endswith(dist):
            release = release[: -len(dist)]
            break

    # Parse %global and %define macros defined in the spec
    macros: dict[str, str] = {}
    for line in spec.splitlines():
        macro_match = re.match(r"^%(?:global|define)\s+(\w+)\s+(.+)$", line)
        if macro_match:
            macros[macro_match.group(1)] = macro_match.group(2).strip()

    # Expand %autorelease or %{autorelease} (with optional -b <base> flag)
    def parse_autorelease(rel_str: str) -> str | None:
        clean = rel_str.strip()
        if clean.startswith("%{autorelease") and clean.endswith("}"):
            clean = "%" + clean[2:-1]
        if clean == "%autorelease" or clean.startswith("%autorelease "):
            b_match = re.search(r"-b\s*(\S+)", clean)
            if b_match:
                return b_match.group(1)
            return "1"
        return None

    auto = parse_autorelease(release)
    if auto is not None:
        return auto

    release = _strip_conditional_macros(release)

    # Expand referenced %{macro} definitions
    for _ in range(5):
        expanded = False
        for k, v in macros.items():
            pattern = f"%{{{k}}}"
            if pattern in release:
                release = release.replace(pattern, v)
                expanded = True
        if not expanded:
            break

    release = _strip_conditional_macros(release)

    auto = parse_autorelease(release)
    if auto is not None:
        return auto

    if "%" in release:
        raise BumpError(
            f"Release: {match.group(1)} is built from macros; bump it by hand "
            "rather than against a baseline that cannot be compared"
        )
    return release


def suffix(entry: dict, release: str) -> str:
    """The disttag suffix for one package, given its current spec release."""
    bump = entry.get("dist_bump")
    if bump is None:
        return ""
    if not isinstance(bump, dict) or {"count", "baseline"} - set(bump):
        raise BumpError(
            'dist_bump must be {"count": N, "baseline": "<the Release: it applies to>"}'
        )
    if str(bump["baseline"]) != release:
        # Fedora moved. The counter answered "same release, built again",
        # which is no longer the question.
        return ""
    return f".{bump['count']}"


def main(name: str) -> str:
    entry = source_locks(ROOT).get(name)
    if entry is None or entry.get("dist_bump") is None:
        return ""
    specs = sorted((ROOT / "packages" / name).glob("*.spec"))
    if not specs:
        raise BumpError(f"{name} records a dist_bump but has no spec")
    return suffix(entry, spec_release(specs[0].read_text(), spec_path=specs[0]))


if __name__ == "__main__":
    try:
        print(main(sys.argv[1]), end="")
    except BumpError as error:
        print(f"{sys.argv[1]}: {error}", file=sys.stderr)
        raise SystemExit(1) from error
