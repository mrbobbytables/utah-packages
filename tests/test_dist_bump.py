#!/usr/bin/env python3

import unittest

from tools.dist_bump import BumpError, spec_release, suffix


class SpecReleaseTests(unittest.TestCase):
    def test_strips_the_dist_macro(self) -> None:
        self.assertEqual(spec_release("Name: x\nRelease: 3%{?dist}\n"), "3")
        self.assertEqual(spec_release("Release: 0.1%{dist}\n"), "0.1")

    def test_keeps_a_release_with_no_dist_macro(self) -> None:
        self.assertEqual(spec_release("Release: 7\n"), "7")

    def test_refuses_a_release_built_from_macros(self) -> None:
        # nodejs and kernel-headers specrelease do this when unresolvable.
        # Comparing the literal string against a baseline would compare two things
        # that are not releases.
        with self.assertRaises(BumpError):
            spec_release("Release: %{krb5_release}%{?dist}\n")

    def test_expands_autorelease_default(self) -> None:
        self.assertEqual(spec_release("Release: %autorelease\n"), "1")
        self.assertEqual(spec_release("Release: %{autorelease}\n"), "1")

    def test_expands_autorelease_with_base_flag(self) -> None:
        self.assertEqual(spec_release("Release: %autorelease -b3\n"), "3")
        self.assertEqual(spec_release("Release: %{autorelease -b 5}\n"), "5")

    def test_evaluates_spec_globals_and_conditionals(self) -> None:
        pipewire = (
            "%global baserelease 3\n"
            "Release: %{baserelease}%{?snapdate:.%{snapdate}git%{shortcommit}}%{?dist}\n"
        )
        self.assertEqual(spec_release(pipewire), "3")

        libxcursor = (
            "%global gitversion 8f677eaea\n"
            "Release: 5%{?gitdate:.%{gitdate}git%{gitversion}}%{?dist}\n"
        )
        self.assertEqual(spec_release(libxcursor), "5")

        firefox = (
            "Release: 1%{?pre_tag}%{?dist}\n"
        )
        self.assertEqual(spec_release(firefox), "1")

        samba = (
            "%global samba_release %autorelease\n"
            "Release: %{samba_release}\n"
        )
        self.assertEqual(spec_release(samba), "1")

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


if __name__ == "__main__":
    unittest.main()
