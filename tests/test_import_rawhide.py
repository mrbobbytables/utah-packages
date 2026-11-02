#!/usr/bin/env python3

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import import_rawhide
from tools.import_rawhide import validate_branch, validate_package


class ImportRawhideValidationTests(unittest.TestCase):
    def test_valid_package_names(self) -> None:
        for name in ["gcc", "wireguard-tools", "adw_gtk3_theme", "pkg123", "a-b_c", "vid.stab"]:
            with self.subTest(name=name):
                validate_package(name)

    def test_invalid_package_names(self) -> None:
        for name in ["", "-starts-with-hyphen", "--option", "name with spaces", "pkg;rm -rf", "pkg$(id)", "pkg`id`", "pkg/name", ".hidden", "..", "pkg..name"]:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    validate_package(name)

    def test_valid_branch_names(self) -> None:
        for branch in ["rawhide", "f41", "f42", "main", "import/branch-name", "rel-1.0"]:
            with self.subTest(branch=branch):
                validate_branch(branch)

    def test_invalid_branch_names(self) -> None:
        for branch in ["", "-starts-with-hyphen", "--upload-pack=evil", "branch with spaces", "branch;echo injection", "branch..traversal", "branch`whoami`", "branch$(whoami)"]:
            with self.subTest(branch=branch):
                with self.assertRaises(ValueError):
                    validate_branch(branch)



def git(*args: str, cwd: Path) -> str:
    return subprocess.check_output(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, text=True,
    ).strip()


class ImportRawhideCommandLineTests(unittest.TestCase):
    """``main()`` against a local repository standing in for src.fedoraproject.org.

    The command line is what import-rawhide-package.yml runs. Its guards are the
    ones that matter: a pinned ``--ref`` must be on the named branch, and an
    existing recipe is never overwritten unless ``--replace`` asks for it.
    """

    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="import-rawhide-test-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)], check=False)
        self.remote = self.root / "remotes" / "demo.git"
        self.remote.mkdir(parents=True)
        git("init", "-q", "-b", "rawhide", cwd=self.remote)
        (self.remote / "demo.spec").write_text("Name: demo\n")
        (self.remote / "old.patch").write_text("old\n")
        git("add", "-A", cwd=self.remote)
        git("commit", "-qm", "one", cwd=self.remote)
        self.first = git("rev-parse", "HEAD", cwd=self.remote)
        (self.remote / "old.patch").unlink()
        (self.remote / "new.patch").write_text("new\n")
        git("add", "-A", cwd=self.remote)
        git("commit", "-qm", "two", cwd=self.remote)
        self.head = git("rev-parse", "HEAD", cwd=self.remote)
        self.head_tree = git("rev-parse", "HEAD^{tree}", cwd=self.remote)
        git("checkout", "-q", "-b", "side", self.first, cwd=self.remote)
        (self.remote / "side.patch").write_text("side\n")
        git("add", "-A", cwd=self.remote)
        git("commit", "-qm", "side", cwd=self.remote)
        self.side = git("rev-parse", "HEAD", cwd=self.remote)
        git("checkout", "-q", "rawhide", cwd=self.remote)
        self.template = f"file://{self.root}/remotes/{{package}}.git"
        self.packages = self.root / "packages"

    def main(self, *args: str) -> tuple[int, str]:
        argv = ["import_rawhide.py", *args,
                "--remote-template", self.template, "--destination", str(self.packages)]
        stdout = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout), \
                contextlib.redirect_stderr(io.StringIO()):
            code = import_rawhide.main()
        return code, stdout.getvalue()

    def files(self) -> list[str]:
        return sorted(p.name for p in (self.packages / "demo").iterdir())

    def test_imports_the_branch_head_with_provenance(self) -> None:
        code, out = self.main("demo")
        self.assertEqual(code, 0)
        self.assertEqual(self.files(), [".hummingbird-upstream.json", "demo.spec", "new.patch"])
        record = json.loads((self.packages / "demo" / ".hummingbird-upstream.json").read_text())
        self.assertEqual(json.loads(out), record)
        self.assertEqual(record["package"], "demo")
        self.assertEqual(record["branch"], "rawhide")
        self.assertEqual(record["remote"], self.template.format(package="demo"))
        self.assertEqual(record["commit"], self.head)
        self.assertEqual(record["tree"], self.head_tree)

    def test_a_pinned_ref_on_the_branch_imports_that_commit(self) -> None:
        code, _ = self.main("demo", "--ref", self.first)
        self.assertEqual(code, 0)
        self.assertEqual(self.files(), [".hummingbird-upstream.json", "demo.spec", "old.patch"])
        record = json.loads((self.packages / "demo" / ".hummingbird-upstream.json").read_text())
        self.assertEqual(record["commit"], self.first)

    def test_a_pinned_ref_off_the_branch_is_refused(self) -> None:
        """A commit that only exists on another branch was never built from rawhide."""
        with self.assertRaises(SystemExit) as raised:
            self.main("demo", "--ref", self.side)
        self.assertEqual(str(raised.exception), f"{self.side} is not on rawhide")
        self.assertFalse((self.packages / "demo").exists())

    def test_an_existing_recipe_is_refused_before_cloning(self) -> None:
        (self.packages / "demo").mkdir(parents=True)
        (self.packages / "demo" / "local.patch").write_text("keep\n")
        with mock.patch.object(import_rawhide, "clone") as clone:
            with self.assertRaises(SystemExit) as raised:
                self.main("demo")
        clone.assert_not_called()
        self.assertIn("destination already exists", str(raised.exception))
        self.assertEqual(self.files(), ["local.patch"])

    def test_replace_swaps_an_existing_recipe_wholesale(self) -> None:
        (self.packages / "demo").mkdir(parents=True)
        (self.packages / "demo" / "local.patch").write_text("stale\n")
        code, _ = self.main("demo", "--replace")
        self.assertEqual(code, 0)
        self.assertEqual(self.files(), [".hummingbird-upstream.json", "demo.spec", "new.patch"])

    def test_invalid_arguments_are_refused_before_cloning(self) -> None:
        cases = {
            "package": ("../demo",),
            "branch": ("demo", "--branch=--upload-pack=evil"),
            "short ref": ("demo", "--ref", self.head[:12]),
            "symbolic ref": ("demo", "--ref", "HEAD"),
            "uppercase ref": ("demo", "--ref", self.head.upper()),
        }
        for label, args in cases.items():
            with self.subTest(label), mock.patch.object(import_rawhide, "clone") as clone:
                with self.assertRaises(SystemExit) as raised:
                    self.main(*args)
                clone.assert_not_called()
                self.assertIsInstance(raised.exception.code, str)
        self.assertFalse(self.packages.exists())

    def test_a_missing_branch_fails_without_writing_a_recipe(self) -> None:
        with self.assertRaises(subprocess.CalledProcessError):
            with mock.patch("sys.stderr", io.StringIO()):
                self.main("demo", "--branch", "f99")
        self.assertFalse((self.packages / "demo").exists())

    def test_extract_reports_a_failed_archive_even_when_tar_accepts_it(self) -> None:
        """tar may read an empty stream as success; git archive's status still counts."""
        accepted = subprocess.CompletedProcess(["tar"], 0)
        with mock.patch.object(import_rawhide.subprocess, "run", return_value=accepted), \
                self.assertRaises(subprocess.CalledProcessError) as raised:
            with contextlib.redirect_stderr(io.StringIO()):
                import_rawhide.extract(self.remote, "0" * 40, self.root / "out")
        self.assertEqual(raised.exception.cmd, ["git", "archive", "0" * 40])
