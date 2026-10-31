#!/usr/bin/env python3
"""The Pages catalog is rendered from the published image's repodata layer."""

import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest import mock

from tools import package_index
from tools.package_index import category, group, lead_rank, parse_primary

PRIMARY = """<?xml version="1.0" encoding="UTF-8"?>
<metadata xmlns="http://linux.duke.edu/metadata/common"
          xmlns:rpm="http://linux.duke.edu/metadata/rpm" packages="4">
{packages}
</metadata>
"""
PACKAGE = """<package type="rpm">
  <name>{name}</name><arch>x86_64</arch>
  <version epoch="0" ver="{ver}" rel="1.hum1.bfin"/>
  <summary>{summary}</summary><description>{summary}.</description>
  <url>https://example.org/{source}</url>
  <time file="1" build="{build}"/>
  <size package="{size}" installed="{installed}" archive="0"/>
  <format>
    <rpm:license>MIT</rpm:license>
    <rpm:sourcerpm>{source}-{ver}-1.hum1.bfin.src.rpm</rpm:sourcerpm>
  </format>
</package>"""
REPOMD = """<?xml version="1.0" encoding="UTF-8"?>
<repomd xmlns="http://linux.duke.edu/metadata/repo">
  <data type="filelists"><location href="repodata/abc-filelists.xml.gz"/></data>
  <data type="primary"><location href="repodata/def-primary.xml.gz"/></data>
</repomd>
"""


def package(name, source, summary, ver="1.0", build=100, size=10, installed=40):
    return PACKAGE.format(
        name=name, source=source, summary=summary, ver=ver,
        build=build, size=size, installed=installed,
    )


def primary_xml() -> bytes:
    return PRIMARY.format(
        packages="\n".join(
            [
                package("libjxl-doc", "jpegxl", "Documentation for JPEG-XL", "0.11"),
                package("libjxl", "jpegxl", "Library files for JPEG-XL", "0.11", build=300),
                package("libjxl-devel", "jpegxl", "Development files", "0.11"),
                package("mesa-libGL", "mesa", "Mesa libGL runtime", "26.2"),
            ]
        )
    ).encode()


def layer(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def repodata_layer() -> bytes:
    return layer(
        {
            "repository/repodata/repomd.xml": REPOMD.encode(),
            "repository/repodata/def-primary.xml.gz": gzip.compress(primary_xml()),
            "repository/repodata/abc-filelists.xml.gz": gzip.compress(b"<x/>"),
        }
    )


CONFIG = {
    "created": "2026-10-15T03:47:31Z",
    "config": {
        "Labels": {
            "org.opencontainers.image.revision": "90ea7804",
            "org.projectbluefin.factory.run": "42",
            "org.projectbluefin.factory.state": json.dumps(
                {"inputs": {"jpegxl": "a", "mesa": "b"}, "failed": {"mesa": "b"}}
            ),
        }
    },
}


class RepodataTests(unittest.TestCase):
    def test_primary_is_found_through_repomd(self) -> None:
        xml = package_index.primary_from_layer(repodata_layer())
        self.assertEqual(xml, primary_xml())

    def test_layer_without_repodata_is_refused(self) -> None:
        with self.assertRaises(SystemExit):
            package_index.primary_from_layer(layer({"repository/x.rpm": b""}))

    def test_parse_primary_reads_each_binary(self) -> None:
        rpms = parse_primary(primary_xml())
        self.assertEqual(len(rpms), 4)
        jxl = next(r for r in rpms if r["name"] == "libjxl")
        self.assertEqual(jxl["version"], "0.11")
        self.assertEqual(jxl["release"], "1.hum1.bfin")
        self.assertEqual(jxl["license"], "MIT")
        self.assertEqual(jxl["sourcerpm"], "jpegxl-0.11-1.hum1.bfin.src.rpm")
        self.assertEqual((jxl["size"], jxl["installed"], jxl["buildtime"]), (10, 40, 300))

    def test_decompress_formats(self) -> None:
        import lzma

        self.assertEqual(package_index.decompress("p.xml.gz", gzip.compress(b"a")), b"a")
        self.assertEqual(package_index.decompress("p.xml.xz", lzma.compress(b"b")), b"b")
        self.assertEqual(package_index.decompress("p.xml", b"c"), b"c")


class GroupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "config").mkdir()
        (self.root / "config" / "upstream-sources.json").write_text(
            json.dumps({"packages": [{"name": "jpegxl", "version": "0.11", "url": "https://u/jxl.tar.gz"}]})
        )
        (self.root / "packages" / "jpegxl").mkdir(parents=True)
        (self.root / "packages" / "jpegxl" / ".hummingbird-upstream.json").write_text(
            json.dumps({"remote": "https://src.fedoraproject.org/rpms/jpegxl.git", "commit": "f00"})
        )

    def test_binaries_fold_into_their_source(self) -> None:
        sources = {p["name"]: p for p in group(parse_primary(primary_xml()), self.root, {"mesa"})}
        self.assertEqual(sorted(sources), ["jpegxl", "mesa"])
        jxl = sources["jpegxl"]
        self.assertEqual(jxl["version"], "0.11")
        self.assertEqual([r["name"] for r in jxl["rpms"]], ["libjxl", "libjxl-devel", "libjxl-doc"])
        self.assertEqual((jxl["size"], jxl["installed"], jxl["buildtime"]), (30, 120, 300))
        self.assertEqual(jxl["upstream"]["url"], "https://u/jxl.tar.gz")
        self.assertEqual(jxl["recipe"]["commit"], "f00")
        self.assertFalse(jxl["failing"])
        self.assertTrue(sources["mesa"]["failing"])

    def test_summary_comes_from_the_runtime_not_the_docs(self) -> None:
        sources = {p["name"]: p for p in group(parse_primary(primary_xml()), self.root, set())}
        self.assertEqual(sources["jpegxl"]["summary"], "Library files for JPEG-XL")

    def test_lead_rank(self) -> None:
        names = ["foo-doc", "foo-devel", "libfoo", "foo", "foo-debuginfo"]
        ranked = sorted(names, key=lambda n: lead_rank("foo", n))
        self.assertEqual(ranked, ["foo", "libfoo", "foo-devel", "foo-doc", "foo-debuginfo"])

    def test_categories(self) -> None:
        self.assertEqual(category("gstreamer1-plugins-good"), "Multimedia")
        self.assertEqual(category("gnome-shell"), "GNOME & GTK")
        self.assertEqual(category("mesa"), "Graphics & display")
        self.assertEqual(category("linux-firmware"), "Firmware & boot")
        self.assertEqual(category("google-noto-sans-cjk-vf-fonts"), "Fonts & i18n")
        self.assertEqual(category("python-psutil"), "Libraries")
        self.assertEqual(category("abseil-cpp"), "Libraries")

    def test_at_most_eight_shelves(self) -> None:
        # The site colours shelves from an eight-slot palette; Libraries is
        # the fallback and takes the last slot.
        self.assertLessEqual(len(package_index.CATEGORIES) + 1, 8)


class CatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "config").mkdir()
        (self.root / "config" / "upstream-sources.json").write_text(json.dumps({"packages": []}))

    def test_labels_and_totals(self) -> None:
        payload = package_index.catalog(
            CONFIG, "sha256:d", parse_primary(primary_xml()),
            image="ghcr.io/o/utah-packages:latest", root=self.root,
        )
        self.assertEqual(payload["image"]["revision"], "90ea7804")
        self.assertEqual(payload["image"]["run"], "42")
        self.assertEqual(payload["image"]["digest"], "sha256:d")
        self.assertEqual(payload["totals"]["sources"], 2)
        self.assertEqual(payload["totals"]["rpms"], 4)
        self.assertEqual(payload["totals"]["failing"], ["mesa"])

    def test_unreadable_state_label_is_no_failures(self) -> None:
        config = {"config": {"Labels": {"org.projectbluefin.factory.state": "{"}}}
        payload = package_index.catalog(
            config, "", [], image="x", root=self.root
        )
        self.assertEqual(payload["totals"]["failing"], [])


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def test_offline_render(self) -> None:
        (self.tmp / "layer.tgz").write_bytes(repodata_layer())
        (self.tmp / "config.json").write_text(json.dumps(CONFIG))
        out = self.tmp / "site" / "packages.json"
        code = package_index.main(
            ["--layer", str(self.tmp / "layer.tgz"), "--config", str(self.tmp / "config.json"),
             "--output", str(out)]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.read_text())
        self.assertEqual(payload["image"]["ref"], "ghcr.io/projectbluefin/utah-packages:latest")
        self.assertEqual(payload["totals"]["rpms"], 4)

    def test_registry_fetch_reads_only_the_first_layer(self) -> None:
        blob = repodata_layer()
        manifest = json.dumps(
            {
                "config": {"digest": "sha256:cfg"},
                "layers": [
                    {"digest": "sha256:meta", "size": len(blob)},
                    {"digest": "sha256:rpms", "size": 2 * 1024**3},
                ],
            }
        ).encode()
        served = {
            "/token": json.dumps({"token": "t"}).encode(),
            "/manifests/main": manifest,
            "/blobs/sha256:cfg": json.dumps(CONFIG).encode(),
            "/blobs/sha256:meta": blob,
        }
        fetched = []

        def fake_get(url, headers):
            fetched.append(url)
            for suffix, data in served.items():
                if suffix in url:
                    return data
            raise AssertionError(f"unexpected fetch {url}")

        with mock.patch.object(package_index, "_get", fake_get):
            config, digest, layer_blob = package_index.fetch_image("o/utah-packages", "main")
        self.assertEqual(layer_blob, blob)
        self.assertEqual(config["created"], CONFIG["created"])
        self.assertEqual(digest, "sha256:" + hashlib.sha256(manifest).hexdigest())
        self.assertFalse(any("sha256:rpms" in url for url in fetched))

    def test_oversized_first_layer_is_refused(self) -> None:
        manifest = json.dumps(
            {"config": {"digest": "c"}, "layers": [{"digest": "l", "size": 2 * 1024**3}]}
        ).encode()

        def fake_get(url, headers):
            return json.dumps({"token": "t"}).encode() if "/token" in url else manifest

        with mock.patch.object(package_index, "_get", fake_get):
            with self.assertRaises(SystemExit):
                package_index.fetch_image("o/utah-packages", "latest")


if __name__ == "__main__":
    unittest.main()
