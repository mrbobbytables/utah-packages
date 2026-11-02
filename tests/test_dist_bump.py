#!/usr/bin/env python3

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.dist_bump as dist_bump
from tools.dist_bump import BumpError, spec_release, suffix

REPO = Path(__file__).resolve().parent.parent


def make_root(root: Path, entries: list[dict], specs: dict[str, dict[str, str]]) -> None:
    """A minimal factory tree: the source locks and each package's spec files."""
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "upstream-sources.json").write_text(
        json.dumps({"packages": entries})
    )
    for name, files in specs.items():
        package = root / "packages" / name
        package.mkdir(parents=True, exist_ok=True)
        for filename, text in files.items():
            (package / filename).write_text(text)


class SpecReleaseTests(unittest.TestCase):
    def test_strips_the_dist_macro(self) -> None:
        self.assertEqual(spec_release("Name: x\nRelease: 3%{?dist}\n"), "3")
        self.assertEqual(spec_release("Release: 0.1%{dist}\n"), "0.1")

    def test_keeps_a_release_with_no_dist_macro(self) -> None:
        self.assertEqual(spec_release("Release: 7\n"), "7")

    def test_extracts_the_leading_release_from_sub_macros(self) -> None:
        # The literal release before the first macro is stable across rebuilds,
        # so it is what a baseline compares against; trailing optional macros
        # (gitdate, pre_tag) are ignored rather than treated as uncomparable.
        self.assertEqual(
            spec_release(
                "Release: 5%{?gitdate:.%{gitdate}git%{gitversion}}%{?dist}\n"
            ),
            "5",
        )
        self.assertEqual(spec_release("Release: 1%{?pre_tag}%{?dist}\n"), "1")

    def test_returns_no_release_for_a_purely_macro_release(self) -> None:
        # %autorelease, %{baserelease}, krb5's %{krb5_release}: no literal
        # segment to compare, so the bump is skipped (None), not crashed on.
        for release in (
            "Release: %{krb5_release}%{?dist}\n",
            "Release: %{autorelease}\n",
            "Release:        %autorelease -b3\n",
            "Release: %{baserelease}%{?snapdate:.%{snapdate}git%{shortcommit}}%{?dist}\n",
        ):
            self.assertIsNone(spec_release(release))

    def test_reports_a_spec_with_no_release(self) -> None:
        with self.assertRaises(BumpError):
            spec_release("Name: x\nVersion: 1\n")


class SuffixTests(unittest.TestCase):
    def test_no_bump_means_no_suffix(self) -> None:
        self.assertEqual(suffix({"name": "x"}, "3"), "")

    def test_applies_the_count_while_the_baseline_holds(self) -> None:
        entry = {"dist_bump": {"count": 1, "baseline": "3"}}
        self.assertEqual(suffix(entry, "3"), ".1")

    def test_retires_the_count_once_fedora_moves(self) -> None:
        # The whole point of the baseline. Release 4 already outranks anything
        # published as 3.bfin.1, so claiming .1 again would assert a rebuild
        # that never happened.
        entry = {"dist_bump": {"count": 1, "baseline": "3"}}
        self.assertEqual(suffix(entry, "4"), "")

    def test_compares_a_numeric_baseline_as_written(self) -> None:
        entry = {"dist_bump": {"count": 2, "baseline": 3}}
        self.assertEqual(suffix(entry, "3"), ".2")

    def test_a_multi_segment_release_is_still_just_a_string(self) -> None:
        entry = {"dist_bump": {"count": 1, "baseline": "0.1"}}
        self.assertEqual(suffix(entry, "0.1"), ".1")
        self.assertEqual(suffix(entry, "0.2"), "")

    def test_rejects_the_bare_integer_shape(self) -> None:
        # The shape this file used to accept. It cannot say what release it
        # was counted against, which is the bug.
        with self.assertRaises(BumpError):
            suffix({"dist_bump": 1}, "3")

    def test_rejects_a_bump_missing_its_baseline(self) -> None:
        with self.assertRaises(BumpError):
            suffix({"dist_bump": {"count": 1}}, "3")


class MainTests(unittest.TestCase):
    """main() is what build-stage.yml captures as DIST_BUMP for every build."""

    BUMP = {"count": 1, "baseline": "47"}

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        patcher = mock.patch.object(dist_bump, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, name: str) -> tuple[str, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = dist_bump.main(name)
        return result, stderr.getvalue()

    def test_a_package_with_no_source_lock_gets_no_suffix(self) -> None:
        make_root(self.root, [{"name": "other", "dist_bump": self.BUMP}], {})
        self.assertEqual(self.run_main("absent"), ("", ""))

    def test_a_lock_without_a_bump_needs_no_spec(self) -> None:
        # No spec on disk: an unbumped package must not be read at all.
        make_root(self.root, [{"name": "plain"}], {})
        self.assertEqual(self.run_main("plain"), ("", ""))

    def test_an_explicit_null_bump_is_no_bump(self) -> None:
        make_root(self.root, [{"name": "plain", "dist_bump": None}], {})
        self.assertEqual(self.run_main("plain"), ("", ""))

    def test_applies_the_count_while_the_spec_release_matches(self) -> None:
        make_root(
            self.root,
            [{"name": "atm", "dist_bump": self.BUMP}],
            {"atm": {"atm.spec": "Name: atm\nRelease: 47%{?dist}\n"}},
        )
        self.assertEqual(self.run_main("atm"), (".1", ""))

    def test_retires_the_count_once_the_spec_release_moves(self) -> None:
        make_root(
            self.root,
            [{"name": "atm", "dist_bump": self.BUMP}],
            {"atm": {"atm.spec": "Name: atm\nRelease: 48%{?dist}\n"}},
        )
        self.assertEqual(self.run_main("atm"), ("", ""))

    def test_reads_the_first_spec_in_sorted_order(self) -> None:
        make_root(
            self.root,
            [{"name": "atm", "dist_bump": self.BUMP}],
            {
                "atm": {
                    "b.spec": "Release: 48%{?dist}\n",
                    "a.spec": "Release: 47%{?dist}\n",
                    "notes.txt": "Release: 99\n",
                }
            },
        )
        self.assertEqual(self.run_main("atm"), (".1", ""))

    def test_a_bump_with_no_spec_is_an_error(self) -> None:
        make_root(self.root, [{"name": "atm", "dist_bump": self.BUMP}], {"atm": {}})
        with self.assertRaisesRegex(BumpError, "atm records a dist_bump but has no spec"):
            dist_bump.main("atm")

    def test_a_spec_with_no_release_line_is_an_error(self) -> None:
        make_root(
            self.root,
            [{"name": "atm", "dist_bump": self.BUMP}],
            {"atm": {"atm.spec": "Name: atm\nVersion: 1\n"}},
        )
        with self.assertRaisesRegex(BumpError, "no Release: line"):
            dist_bump.main("atm")

    def test_a_purely_macro_release_skips_the_bump_out_loud(self) -> None:
        # build-stage.yml only captures stdout, so the skip must reach stderr
        # or a recorded rebuild vanishes without a trace.
        make_root(
            self.root,
            [{"name": "atm", "dist_bump": self.BUMP}],
            {"atm": {"atm.spec": "Release: %autorelease\n"}},
        )
        result, stderr = self.run_main("atm")
        self.assertEqual(result, "")
        self.assertEqual(
            stderr, "atm: dist_bump skipped, Release: has no comparable baseline\n"
        )

    def test_a_malformed_bump_reaches_the_caller(self) -> None:
        make_root(
            self.root,
            [{"name": "atm", "dist_bump": 1}],
            {"atm": {"atm.spec": "Release: 47%{?dist}\n"}},
        )
        with self.assertRaisesRegex(BumpError, "dist_bump must be"):
            dist_bump.main("atm")


class CommandLineTests(unittest.TestCase):
    """The script as build-stage.yml runs it: DIST_BUMP=\"$(python3 tools/dist_bump.py PKG)\"."""

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(
            REPO / "tools",
            self.root / "tools",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        make_root(
            self.root,
            [
                {"name": "atm", "dist_bump": {"count": 2, "baseline": "47"}},
                {"name": "lost", "dist_bump": {"count": 1, "baseline": "1"}},
                {"name": "plain"},
            ],
            {"atm": {"atm.spec": "Release: 47%{?dist}\n"}, "lost": {}},
        )

    def run_cli(self, name: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(self.root / "tools" / "dist_bump.py"), name],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_prints_the_suffix_with_no_trailing_newline(self) -> None:
        result = self.run_cli("atm")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, ".2", ""))

    def test_prints_nothing_for_an_unbumped_package(self) -> None:
        result = self.run_cli("plain")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_a_bump_error_fails_the_step_and_names_the_package(self) -> None:
        # set -euo pipefail in build-stage.yml turns this exit into a failed
        # build instead of an RPM built without its recorded suffix.
        result = self.run_cli("lost")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(
            result.stderr, "lost: lost records a dist_bump but has no spec\n"
        )


if __name__ == "__main__":
    unittest.main()
