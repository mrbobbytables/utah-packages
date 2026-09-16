#!/usr/bin/env python3
"""Coverage for tools/rebuild_matrix.py: skip/rebuild selection, stage outputs,
overflow detection, and workflow delegation.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from tools.rebuild_matrix import (
    StageOverflowError,
    assert_workflow_delegates,
    git_changed_packages,
    load_workflow,
    main,
    normalize_version,
    parse_primary_xml,
    select_builds,
    stage_outputs,
)


class VersionNormalizationTests(unittest.TestCase):
    def test_replaces_tilde_with_dot(self):
        self.assertEqual(normalize_version("51~beta"), "51.beta")
        self.assertEqual(normalize_version("1.0~rc1~2"), "1.0.rc1.2")

    def test_standard_version_unchanged(self):
        self.assertEqual(normalize_version("1.2.3"), "1.2.3")
        self.assertEqual(normalize_version(""), "")


class SelectBuildsTests(unittest.TestCase):
    def setUp(self):
        self.packages = [
            {"name": "pkg-a", "version": "1.0.0", "stage": 0},
            {"name": "pkg-b", "version": "2.0~beta", "stage": 1},
            {"name": "pkg-c", "version": "3.0.0", "stage": 2},
        ]
        self.packages_dict = {p["name"]: p for p in self.packages}

    def test_skip_when_published_and_unchanged(self):
        published = {
            "pkg-a": "1.0.0",
            "pkg-b": "2.0.beta",  # normalized matches 2.0~beta
            "pkg-c": "3.0.0",
        }
        build = select_builds(self.packages, published=published, changed=set(), full=False)
        self.assertEqual(build, [])

    def test_rebuild_when_not_in_published(self):
        published = {
            "pkg-a": "1.0.0",
            # pkg-b not published
            "pkg-c": "3.0.0",
        }
        build = select_builds(self.packages, published=published, changed=set(), full=False)
        self.assertEqual([p["name"] for p in build], ["pkg-b"])

    def test_rebuild_when_version_changed(self):
        published = {
            "pkg-a": "0.9.9",  # older version published
            "pkg-b": "2.0~beta",
            "pkg-c": "3.0.0",
        }
        build = select_builds(self.packages, published=published, changed=set(), full=False)
        self.assertEqual([p["name"] for p in build], ["pkg-a"])

    def test_rebuild_when_recipe_changed(self):
        published = {
            "pkg-a": "1.0.0",
            "pkg-b": "2.0~beta",
            "pkg-c": "3.0.0",
        }
        changed = {"pkg-c"}
        build = select_builds(self.packages, published=published, changed=changed, full=False)
        self.assertEqual([p["name"] for p in build], ["pkg-c"])

    def test_full_rebuilds_all_packages(self):
        published = {
            "pkg-a": "1.0.0",
            "pkg-b": "2.0~beta",
            "pkg-c": "3.0.0",
        }
        build = select_builds(self.packages, published=published, changed=set(), full=True)
        self.assertEqual([p["name"] for p in build], ["pkg-a", "pkg-b", "pkg-c"])

    def test_empty_published_rebuilds_all(self):
        build = select_builds(self.packages, published={}, changed=set(), full=False)
        self.assertEqual([p["name"] for p in build], ["pkg-a", "pkg-b", "pkg-c"])

    def test_accepts_dict_input(self):
        published = {"pkg-a": "1.0.0"}
        build = select_builds(self.packages_dict, published=published, changed=set(), full=False)
        self.assertEqual([p["name"] for p in build], ["pkg-b", "pkg-c"])


class StageOutputsTests(unittest.TestCase):
    def test_stage_distribution(self):
        build = [
            {"name": "pkg0", "stage": 0},
            {"name": "pkg0_default"},  # stage defaults to 0
            {"name": "pkg1", "stage": 1},
            {"name": "pkg2", "stage": 2},
            {"name": "pkg3", "stage": 3},
            {"name": "pkg4", "stage": 4},
        ]
        outputs = stage_outputs(build)
        self.assertEqual(
            json.loads(outputs["build_list"]),
            ["pkg0", "pkg0_default", "pkg1", "pkg2", "pkg3", "pkg4"],
        )
        self.assertEqual(json.loads(outputs["stage0"]), ["pkg0", "pkg0_default"])
        self.assertEqual(json.loads(outputs["stage1"]), ["pkg1"])
        self.assertEqual(json.loads(outputs["stage2"]), ["pkg2"])
        self.assertEqual(json.loads(outputs["stage3"]), ["pkg3"])
        self.assertEqual(json.loads(outputs["stage4"]), ["pkg4"])

    def test_empty_build_outputs(self):
        outputs = stage_outputs([])
        self.assertEqual(json.loads(outputs["build_list"]), [])
        for n in range(5):
            self.assertEqual(json.loads(outputs[f"stage{n}"]), [])

    def test_stage_overflow_raises_error(self):
        build = [
            {"name": "valid-pkg", "stage": 2},
            {"name": "overflow-pkg", "stage": 5},
        ]
        with self.assertRaises(StageOverflowError) as ctx:
            stage_outputs(build)
        self.assertIn("no job exists for stage 5 or later", str(ctx.exception))
        self.assertIn("overflow-pkg", str(ctx.exception))
        self.assertTrue(issubclass(StageOverflowError, ValueError))

    def test_stage_overflow_multiple_packages_sorted(self):
        build = [
            {"name": "pkg-z", "stage": 6},
            {"name": "pkg-a", "stage": 5},
        ]
        with self.assertRaises(StageOverflowError) as ctx:
            stage_outputs(build)
        self.assertEqual(
            str(ctx.exception),
            "no job exists for stage 5 or later; reduce the stage of: pkg-a, pkg-z",
        )


class GitChangedPackagesTests(unittest.TestCase):
    def test_invalid_or_empty_base_sha(self):
        self.assertEqual(git_changed_packages(None), set())
        self.assertEqual(git_changed_packages(""), set())
        self.assertEqual(git_changed_packages("invalid-sha"), set())
        self.assertEqual(git_changed_packages("0" * 40), set())


class RepodataParsingTests(unittest.TestCase):
    def test_parse_primary_xml(self):
        xml_content = b"""<?xml version="1.0" encoding="UTF-8"?>
        <metadata xmlns="http://linux.duke.edu/metadata/common">
          <package type="rpm">
            <name>foo-bar</name>
            <arch>x86_64</arch>
            <version epoch="0" ver="1.2.3" rel="1.fc41"/>
          </package>
          <package type="rpm">
            <name>baz</name>
            <arch>noarch</arch>
            <version epoch="0" ver="4.5.6~beta" rel="2.fc41"/>
          </package>
        </metadata>
        """
        parsed = parse_primary_xml(xml_content)
        self.assertEqual(parsed, {"foo-bar": "1.2.3", "baz": "4.5.6~beta"})


class WorkflowDelegationTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow()

    def test_rebuild_rpms_delegates_to_rebuild_matrix(self):
        assert_workflow_delegates(self.workflow)

    def test_assert_delegates_rejects_missing_matrix_step(self):
        broken = {"jobs": {"prepare": {"steps": [{"id": "other"}]}}}
        with self.assertRaises(AssertionError):
            assert_workflow_delegates(broken)

    def test_assert_delegates_rejects_inline_heredoc(self):
        broken = {
            "jobs": {
                "prepare": {
                    "outputs": {f"stage{i}": "" for i in range(5)} | {"build_list": ""},
                    "steps": [
                        {
                            "id": "matrix",
                            "env": {"FULL": "0", "BASE_SHA": ""},
                            "run": "python3 - <<'PY'\nimport json\nPY",
                        }
                    ],
                }
            }
        }
        with self.assertRaises(AssertionError):
            assert_workflow_delegates(broken)


class SourceLockContractTests(unittest.TestCase):
    def test_source_locks_validation_applies_to_resolver(self):
        # If source_locks encounters a duplicate lock or unknown stage,
        # it raises ValueError, aborting matrix resolution before any builds run.
        with (
            patch("tools.rebuild_matrix.source_locks", side_effect=ValueError("duplicate source lock: demo")),
            self.assertRaises(ValueError),
        ):
            main(["--full"])


if __name__ == "__main__":
    unittest.main()
