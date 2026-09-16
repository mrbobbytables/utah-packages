#!/usr/bin/env python3
"""Resolve the rebuild matrix for the Utah package factory.

Determines which packages need rebuilding based on:
1. Whether a full rebuild was requested.
2. Changes to package recipes in git diff.
3. Packages missing from the published repository.
4. Version mismatches between source locks and the published repository.

Extracts the wave assignment (stage0..stage4 and build_list) and guards against
stage-5 overflow.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import subprocess
import sys
import urllib.request
from collections.abc import Iterable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.package_inventory import KNOWN_STAGES, source_locks

REBUILD_WORKFLOW = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "rebuild-rpms.yml"
)
DEFAULT_REPO_URL = "https://projectbluefin.github.io/utah-packages/"


class StageOverflowError(ValueError):
    """Raised when a package requests an unsupported stage index (>= 5)."""


def normalize_version(version: str) -> str:
    """Normalize '~' to '.' so Fedora pre-release versions match upstream."""
    return version.replace("~", ".")


norm = normalize_version


def select_builds(
    packages: Iterable[dict] | dict[str, dict],
    published: dict[str, str] | None = None,
    changed: set[str] | None = None,
    full: bool = False,
) -> list[dict]:
    """Select packages that must be rebuilt.

    A package is rebuilt if:
    - ``full`` is True, or
    - the package name is in ``changed`` (recipe modified in git diff), or
    - the package name is not in ``published`` (never published before), or
    - the published version does not match the source lock version (after '~' to '.' normalization).
    """
    if published is None:
        published = {}
    if changed is None:
        changed = set()
    if isinstance(packages, dict):
        package_list = list(packages.values())
    else:
        package_list = list(packages)

    build = []
    for package in package_list:
        name = package["name"]
        version = package.get("version", "")
        if (
            full
            or name in changed
            or name not in published
            or normalize_version(published[name]) != normalize_version(version)
        ):
            build.append(package)
    return build


def stage_outputs(
    build: Iterable[dict] | dict[str, dict],
    num_stages: int = len(KNOWN_STAGES),
) -> dict[str, str]:
    """Derive GitHub Actions job matrix outputs for the selected packages.

    Returns a mapping containing ``build_list`` and ``stage0`` through ``stage{num_stages-1}``,
    where values are JSON-encoded string lists of package names.

    Raises ``StageOverflowError`` if any package specifies a stage >= ``num_stages``.
    """
    if isinstance(build, dict):
        build_list = list(build.values())
    else:
        build_list = list(build)

    overflow = sorted(p["name"] for p in build_list if (p.get("stage") or 0) >= num_stages)
    if overflow:
        raise StageOverflowError(
            f"no job exists for stage {num_stages} or later; "
            f"reduce the stage of: {', '.join(overflow)}"
        )

    outputs = {"build_list": json.dumps([p["name"] for p in build_list])}
    for n in range(num_stages):
        outputs[f"stage{n}"] = json.dumps(
            [p["name"] for p in build_list if (p.get("stage") or 0) == n]
        )
    return outputs


def git_changed_packages(base_sha: str | None, head: str = "HEAD") -> set[str]:
    """Find package recipe names changed between base_sha and head."""
    if not base_sha or not re.fullmatch(r"[0-9a-f]{40}", base_sha) or set(base_sha) == {"0"}:
        return set()
    try:
        paths = subprocess.check_output(
            ["git", "diff", "--name-only", f"{base_sha}..{head}"],
            text=True,
        ).splitlines()
    except subprocess.SubprocessError as error:
        print(f"WARNING: could not compute git diff against {base_sha}: {error}", file=sys.stderr)
        return set()
    return {
        match.group(1)
        for path in paths
        if (match := re.match(r"^packages/([^/]+)/", path))
    }


def parse_primary_xml(raw_bytes: bytes) -> dict[str, str]:
    """Parse package names and versions from repodata primary xml."""
    published = {}
    for m in re.finditer(
        rb'<package[^>]*>.*?<name>([^<]+)</name>.*?<version[^>]*ver="([^"]+)"',
        raw_bytes,
        re.DOTALL,
    ):
        published[m.group(1).decode()] = m.group(2).decode()
    return published


def fetch_published_packages(base_url: str = DEFAULT_REPO_URL) -> dict[str, str]:
    """Fetch and parse currently published repo packages."""
    if not base_url.endswith("/"):
        base_url += "/"
    try:
        repomd = urllib.request.urlopen(base_url + "repodata/repomd.xml", timeout=60).read().decode()
        match = re.search(r'<location href="([^"]*primary[^"]*)"', repomd)
        if not match:
            raise ValueError("could not find primary repodata location in repomd.xml")
        href = match.group(1)
        raw = urllib.request.urlopen(base_url + href, timeout=120).read()
        if href.endswith(".zst"):
            import zstandard
            stream = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw))
        else:
            stream = gzip.GzipFile(fileobj=io.BytesIO(raw))
        text = stream.read()
        published = parse_primary_xml(text)
        print(f"published repo has {len(published)} packages")
        return published
    except Exception as error:  # noqa: BLE001
        print(f"WARNING: could not read published repo, rebuilding all: {error}", file=sys.stderr)
        return {}


def load_workflow(path: Path = REBUILD_WORKFLOW) -> dict:
    """Load workflow YAML definition."""
    import yaml

    with path.open() as handle:
        return yaml.safe_load(handle)


def assert_workflow_delegates(
    workflow: dict | None = None,
    workflow_path: Path = REBUILD_WORKFLOW,
) -> None:
    """Assert that rebuild-rpms.yml delegates to tools/rebuild_matrix.py rather than an inline heredoc."""
    if workflow is None:
        workflow = load_workflow(workflow_path)
    try:
        prepare = workflow["jobs"]["prepare"]
        steps = prepare["steps"]
    except (KeyError, TypeError) as error:
        raise AssertionError("rebuild-rpms.yml has no prepare job steps") from error

    matrix_step = next((s for s in steps if s.get("id") == "matrix"), None)
    if matrix_step is None:
        raise AssertionError("rebuild-rpms.yml prepare job has no matrix step")

    run_cmd = str(matrix_step.get("run", "")).strip()
    if "tools/rebuild_matrix.py" not in run_cmd:
        raise AssertionError(
            f"matrix step must invoke tools/rebuild_matrix.py, found: {run_cmd!r}"
        )
    if "<<" in run_cmd or "upstream-sources.json" in run_cmd:
        raise AssertionError(
            "matrix step must delegate to tools/rebuild_matrix.py rather than inline heredoc"
        )

    env = matrix_step.get("env", {})
    if "FULL" not in env or "BASE_SHA" not in env:
        raise AssertionError("matrix step must define FULL and BASE_SHA environment variables")

    outputs = prepare.get("outputs", {})
    for expected_key in ("stage0", "stage1", "stage2", "stage3", "stage4", "build_list"):
        if expected_key not in outputs:
            raise AssertionError(f"prepare job must output {expected_key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve Utah package rebuild matrix")
    parser.add_argument("--full", action="store_true", default=None, help="Rebuild all packages")
    parser.add_argument("--base-sha", default=None, help="Base commit SHA for recipe diff")
    args = parser.parse_args(argv)

    full = args.full if args.full is not None else (os.environ.get("FULL") == "1")
    base = args.base_sha if args.base_sha is not None else os.environ.get("BASE_SHA", "")

    root = Path(__file__).resolve().parent.parent

    changed = set()
    if not full:
        changed = git_changed_packages(base)
        if changed:
            print(f"changed package recipes: {', '.join(sorted(changed))}")
        else:
            print("changed package recipes: none")

    published = {}
    if not full:
        published = fetch_published_packages()

    locks = source_locks(root)
    build = select_builds(locks, published=published, changed=changed, full=full)

    build_names = {p["name"] for p in build}
    for package in locks.values():
        name = package["name"]
        version = package.get("version", "")
        if name not in build_names:
            print(f"skip {name} {version}: already published")

    try:
        outputs = stage_outputs(build)
    except StageOverflowError as error:
        raise SystemExit(str(error))

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in outputs.items())

    print(f"will build {len(build)} of {len(locks)} packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
