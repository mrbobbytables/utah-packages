#!/usr/bin/env python3
"""pkgconfig() provides read from the .pc paths a parsed spec's %files ship."""

from pathlib import Path
import subprocess
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "extract_buildrequires.sh"

PARSED_SPEC = """\
Name: libgedit-gtksourceview
BuildRequires: pkgconfig(libgedit-amtk-5) >= 5.11

%install
install -m644 x.pc %{buildroot}/usr/lib64/pkgconfig/install-only.pc

%files -f libgedit-gtksourceview-300.lang
%license COPYING
%doc README.md
/usr/lib64/libgedit-gtksourceview-300.so.*

%files devel
%dir /usr/include/libgedit-gtksourceview-300
%attr(0644,root,root) /usr/lib64/pkgconfig/libgedit-gtksourceview-300.pc
/usr/share/pkgconfig/shared-data.pc
/usr/lib64/pkgconfig/glob-*.pc
/usr/lib64/pkgconfig/

%post devel
echo /usr/lib64/pkgconfig/scriptlet.pc

%changelog
* Mon Oct 19 2026 Someone - 1-1
- moved /usr/lib64/pkgconfig/changelog.pc
"""


def pc_provides(text: str) -> list[str]:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--pc-provides"],
        input=text,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.splitlines()


class PcProvidesTests(unittest.TestCase):
    def test_only_concrete_pc_paths_inside_files_sections(self) -> None:
        self.assertEqual(
            pc_provides(PARSED_SPEC),
            [
                "pkgconfig(libgedit-gtksourceview-300)",
                "pkgconfig(shared-data)",
            ],
        )

    def test_files_directives_keep_the_section_open(self) -> None:
        text = "%files devel\n%doc NEWS\n%ghost /x\n/usr/lib64/pkgconfig/after-doc.pc\n"
        self.assertEqual(pc_provides(text), ["pkgconfig(after-doc)"])

    def test_every_files_section_is_read(self) -> None:
        text = (
            "%files -n libgedit-amtk-devel\n/usr/lib64/pkgconfig/libgedit-amtk-5.pc\n"
            "%prep\n/usr/lib64/pkgconfig/prep.pc\n"
            "%files -n libgedit-gfls-devel\n/usr/lib64/pkgconfig/libgedit-gfls-1.pc\n"
        )
        self.assertEqual(
            pc_provides(text),
            ["pkgconfig(libgedit-amtk-5)", "pkgconfig(libgedit-gfls-1)"],
        )

    def test_no_files_section_provides_nothing(self) -> None:
        self.assertEqual(pc_provides("%install\n/usr/lib64/pkgconfig/a.pc\n"), [])


if __name__ == "__main__":
    unittest.main()
