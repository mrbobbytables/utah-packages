#!/usr/bin/env python3
"""Render the package catalog the GitHub Pages site serves.

The catalog describes what consumers actually receive: the published OCI
image, not the recipes in this checkout. A recipe can be ahead of the image
(not built yet), behind it (a failed build keeps its previous RPMs), or absent
from it entirely, so the index reads the image and only uses the checkout for
context the image does not carry (the upstream tarball, the Fedora recipe
commit, the build lane).

Only layers[0] is fetched. publish-repository.yml builds the image as
``COPY repository/repodata`` then ``COPY repository``, so the first layer is
the repodata alone -- a few MiB -- and the RPMs (gigabytes) are never pulled.
Its labels carry the commit, the run and the factory state, which names the
packages whose latest build failed and still ship an older one.

The site is a read-only view. It is not the retired Pages RPM mirror and must
never become one: the OCI image stays the only publication consumers read.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import lzma
import os
import re
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.package_inventory import source_locks

REGISTRY = "ghcr.io"
STATE_LABEL = "org.projectbluefin.factory.state"
# publish-repository.yml refuses a repodata layer of 64 MiB or more; anything
# bigger here is not the repodata layer and pulling it would fetch the RPMs.
MAX_LAYER = 64 * 1024 * 1024
ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
NS = {
    "common": "http://linux.duke.edu/metadata/common",
    "rpm": "http://linux.duke.edu/metadata/rpm",
    "repo": "http://linux.duke.edu/metadata/repo",
}
# Browsing shelves for the site, matched against the source name in order;
# the first hit wins and anything unmatched (Python modules included) is a
# library. Eight at most: the site colours them from an eight-slot palette.
# They are a reading aid, not a classification the factory relies on.
CATEGORIES = (
    ("Fonts & i18n", r"fonts$|^ibus|^mozc$|^hunspell|^hyphen$|^iso-codes$|^icu$"
     r"|^libthai$|^libdatrie$|^fribidi$|^libunibreak$|^enchant|^libphonenumber$"
     r"|^poppler-data$|^snowball$"),
    ("Firmware & boot", r"firmware|^microcode|^fwupd$|^passim$|^grub2$|^plymouth$"
     r"|^zram-generator$|^anaconda$|^livesys-scripts$|^isomd5sum$"),
    ("Multimedia", r"^gstreamer|^ffmpeg|^pipewire|^wireplumber$|^pulseaudio$|^alsa-"
     r"|^lib(va|vpl|vdpau|ass|aribcaption|bs2b|cdio|dvd|ebur128|freeaptx|lc3"
     r"|ldac|modplug|mysofa|ogg|openmpt|samplerate|shout|sndfile|theora|visual"
     r"|vorbis|vpx|heif|mediainfo|zen|cue|canberra)"
     r"|^intel-(media|mediasdk|vpl|gmmlib)|^(aribb24|cdparanoia|codec2|fdk-aac-free"
     r"|flac|flite|game-music-emu|gsm|ilbc|lame|lpcnetfreedv|mpg123|noopenh264"
     r"|openapv|opencore-amr|opus|orc|rubberband|sbc|soxr|spandsp|speex|srt"
     r"|twolame|vid\.stab|vo-amrwbenc|wavpack|webrtc-audio-processing|xevd|xeve"
     r"|xvidcore|zimg|zvbi|jpegxl|openjpeg|giflib|libexif|exiv2|libgexiv2"
     r"|taglib|totem-pl-parser|librist|libopenmpt|sound-theme-freedesktop"
     r"|ffmpegthumbnailer|libcamera|v4l-utils)$"),
    ("Graphics & display", r"^mesa|^libdrm$|^libglvnd$|^vulkan|^spirv|^wayland"
     r"|^libepoxy$|^libX|^libx|^xcb|^xorg|^x(host|kbcomp|modmap|prop|rdb"
     r"|refresh)$|^setxkbmap$|^libdisplay-info$|^libdecor$|^libei$|^pixman$"
     r"|^igt-gpu-tools$|^libICE$|^libSM$|^waypipe$|^wl-clipboard$|^libpciaccess$"
     r"|^SDL3$|^sdl2-compat$|^graphene$|^highway$|^nvtop$|^startup-notification$"),
    ("GNOME & GTK", r"^gnome-|^gtk|^gdm$|^mutter$|^nautilus$|^libadwaita$|^adw"
     r"|^adwaita|^gjs$|^glycin$|^gcr|^gsettings|^gvfs$|^libgweather$|^gweather"
     r"|^localsearch$|^tecla$|^zenity$|^ptyxis$|^vte|^malcontent|^xdg-desktop-portal"
     r"|^dconf$|^evolution|^libportal$|^gsound$|^json-glib$|^libsoup|^glib-networking$"
     r"|^webkitgtk$|^mozjs|^gobject-introspection$|^at-spi2|^pango$|^cairo$"
     r"|^gdk-pixbuf2$|^librsvg2$|^libnotify$|^libsecret$|^gtksourceview|^libgda$"
     r"|^libgtop2$|^libcloudproviders$|^geoclue2$|^geocode-glib$|^libnma$"
     r"|^gupnp|^gssdp$|^libmanette$|^libgsf$|^libgxps$|^msgraph$|^rest$"
     r"|^colord-gtk$|^hicolor-icon-theme$|^libappindicator$|^libayatana|^libdbusmenu$"
     r"|^accountsservice$|^libxmlb$|^appstream$|^shared-mime-info$|^desktop-file-utils$"
     r"|^xdg-user-dirs|^switcheroo-control$|^iio-sensor-proxy$|^upower$"
     r"|^gnome-shell-extension|^slitherer$|^kde-|^kf5$"),
    ("Hardware", r"^bluez$|^ModemManager$|^libmbim$|^libqmi$|^libqrtr|^udisks2$"
     r"|^libblockdev$|^ddcutil$|^i2c-tools$|^lm_sensors$|^hwdata$|^hwinfo$|^pciutils$"
     r"|^libratbag$|^openrgb$|^libwacom$|^libinput$|^libevdev$|^evtest$"
     r"|^input-remapper$|^mtdev$|^hidapi$|^libgusb$|^libgudev$|^libimobiledevice"
     r"|^usbmuxd$|^libusbmuxd$|^libplist$|^libtatsu$|^libmtp$|^libgphoto2$|^pcsc"
     r"|^tpm2|^iw$|^wireless-regdb$|^wpa_supplicant$|^linux-atm$|^ppp$|^libnvme$"
     r"|^dmidecode$|^libx86emu$|^parted$|^mdadm$|^device-mapper|^ntfs-3g$|^fuse$"
     r"|^squashfs-tools$|^libatasmart$|^libbytesize$|^volume_key$|^fxload$"
     r"|^libfprint$|^fprintd$|^colord$|^cups|^libcups|^libppd$|^ghostscript$|^pdfio$"
     r"|^mobile-broadband-provider-info$|^gpm$|^libburn$|^libisoburn$|^libisofs$"),
    ("Tools & services", r"^containerd$|^runc$|^distrobox$|^flatpak|^git$|^fish$|^zsh$"
     r"|^fzf$|^gum$|^rust-just$|^fastfetch$|^tailscale$|^wireguard-tools$|^xdg-"
     r"|^osinfo|^libosinfo$|^samba$|^wsdd$|^rtkit$|^setools$|^iputils$|^liboping$"
     r"|^lttng-ust$|^xmlrpc-c$|^libnfs$|^libnice$|^libproxy$|^libpcap$|^sassc$"),
)
CATEGORY_RULES = tuple((label, re.compile(pattern)) for label, pattern in CATEGORIES)
SRPM = re.compile(r"^(?P<name>.+)-(?P<version>[^-]+)-(?P<release>[^-]+)\.(?:no)?src\.rpm$")


# --- registry -------------------------------------------------------------


def _get(url: str, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def registry_token(repository: str) -> str:
    """A pull token: anonymous for a public image, else from GITHUB_TOKEN.

    Anonymous goes first because a token scoped to some other repository is
    refused outright, even for an image anyone may pull.
    """
    url = f"https://{REGISTRY}/token?scope=repository:{repository}:pull"
    try:
        return json.loads(_get(url, {}))["token"]
    except urllib.error.HTTPError:
        secret = os.environ.get("GITHUB_TOKEN")
        if not secret:
            raise
    basic = base64.b64encode(f"token:{secret}".encode()).decode()
    return json.loads(_get(url, {"Authorization": f"Basic {basic}"}))["token"]


def fetch_image(repository: str, tag: str) -> tuple[dict, str, bytes]:
    """Return (config, manifest digest, repodata layer) for repository:tag."""
    auth = {"Authorization": f"Bearer {registry_token(repository)}"}
    base = f"https://{REGISTRY}/v2/{repository}"
    raw = _get(f"{base}/manifests/{tag}", {**auth, "Accept": ACCEPT})
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    layer = manifest["layers"][0]
    if layer["size"] >= MAX_LAYER:
        raise SystemExit(
            f"{repository}:{tag} layers[0] is {layer['size']} bytes; "
            "expected the repodata-only layer"
        )
    config = json.loads(_get(f"{base}/blobs/{manifest['config']['digest']}", auth))
    blob = _get(f"{base}/blobs/{layer['digest']}", auth)
    return config, digest, blob


# --- repodata -------------------------------------------------------------


def decompress(name: str, data: bytes) -> bytes:
    if name.endswith(".gz"):
        return gzip.decompress(data)
    if name.endswith(".xz"):
        return lzma.decompress(data)
    if name.endswith(".zst"):
        try:
            from compression import zstd  # Python 3.14+

            return zstd.decompress(data)
        except ImportError:
            return subprocess.run(
                ["zstd", "-dc"], input=data, capture_output=True, check=True
            ).stdout
    return data


def primary_from_layer(blob: bytes) -> bytes:
    """Find repomd.xml in the layer tarball and return primary.xml, decoded."""
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as archive:
        for member in archive:
            if member.isfile() and "/repodata/" in f"/{member.name}":
                handle = archive.extractfile(member)
                if handle is not None:
                    files[member.name.lstrip("./")] = handle.read()
    repomd_name = next((n for n in files if n.endswith("repodata/repomd.xml")), None)
    if repomd_name is None:
        raise SystemExit("repodata layer carries no repodata/repomd.xml")
    prefix = repomd_name[: -len("repodata/repomd.xml")]
    repomd = ET.fromstring(files[repomd_name])
    for data in repomd.findall("repo:data", NS):
        if data.get("type") == "primary":
            href = data.find("repo:location", NS).get("href")
            return decompress(href, files[prefix + href])
    raise SystemExit("repomd.xml names no primary metadata")


def parse_primary(xml: bytes) -> list[dict]:
    """One dict per binary RPM in primary.xml."""
    rpms = []
    for package in ET.fromstring(xml).findall("common:package", NS):
        version = package.find("common:version", NS)
        size = package.find("common:size", NS)
        when = package.find("common:time", NS)
        fmt = package.find("common:format", NS)
        rpms.append(
            {
                "name": package.findtext("common:name", "", NS),
                "arch": package.findtext("common:arch", "", NS),
                "epoch": int(version.get("epoch") or 0),
                "version": version.get("ver", ""),
                "release": version.get("rel", ""),
                "summary": package.findtext("common:summary", "", NS).strip(),
                "description": package.findtext("common:description", "", NS).strip(),
                "url": package.findtext("common:url", "", NS),
                "size": int(size.get("package") or 0),
                "installed": int(size.get("installed") or 0),
                "buildtime": int(when.get("build") or 0),
                "license": fmt.findtext("rpm:license", "", NS),
                "sourcerpm": fmt.findtext("rpm:sourcerpm", "", NS),
            }
        )
    return rpms


# --- catalog --------------------------------------------------------------


def category(name: str) -> str:
    for label, rule in CATEGORY_RULES:
        if rule.search(name):
            return label
    return "Libraries"


def recipe(root: Path, name: str) -> dict:
    path = root / "packages" / name / ".hummingbird-upstream.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def lead_rank(source: str, rpm: str) -> tuple[int, int, str]:
    """Order a source's binaries by how well each speaks for the whole.

    The binary named after its source wins; failing that, a runtime package
    beats a -devel, which beats docs and debug data -- jpegxl ships no
    ``jpegxl`` binary, and its ``-doc`` summary is not what jpegxl is.
    """
    if rpm == source:
        return (0, 0, rpm)
    if re.search(r"-(debuginfo|debugsource|doc|docs|devel-docs|help)$", rpm):
        tier = 3
    elif re.search(r"-(devel|static|tests?)$", rpm):
        tier = 2
    else:
        tier = 1
    return (tier, len(rpm), rpm)


def group(rpms: list[dict], root: Path, failed: set[str]) -> list[dict]:
    """Fold binary RPMs into the source packages they were built from."""
    built: dict[str, list[dict]] = {}
    for rpm in rpms:
        match = SRPM.match(rpm["sourcerpm"])
        built.setdefault(match["name"] if match else rpm["name"], []).append(rpm)

    sources: dict[str, dict] = {}
    for name, members in built.items():
        members.sort(key=lambda r: (lead_rank(name, r["name"]), r["arch"]))
        match = SRPM.match(members[0]["sourcerpm"])
        entry = {
            "name": name,
            "epoch": members[0]["epoch"],
            "version": match["version"] if match else members[0]["version"],
            "release": match["release"] if match else members[0]["release"],
        }
        # Text comes from the best-ranked binary that carries it.
        for key in ("summary", "description", "url", "license"):
            entry[key] = next((r[key] for r in members if r[key]), "")
        entry["buildtime"] = max(r["buildtime"] for r in members)
        entry["size"] = sum(r["size"] for r in members)
        entry["installed"] = sum(r["installed"] for r in members)
        entry["rpms"] = [
            {key: r[key] for key in ("name", "arch", "summary", "size", "installed")}
            for r in members
        ]
        sources[name] = entry

    known = source_locks(root)
    for name, entry in sources.items():
        source = known.get(name, {})
        meta = recipe(root, name)
        entry["upstream"] = {
            "version": source.get("version", ""),
            "url": source.get("url", ""),
        }
        entry["recipe"] = {
            "remote": meta.get("remote", ""),
            "commit": meta.get("commit", ""),
        }
        entry["category"] = category(name)
        entry["lane"] = source.get("build_lane", "hermetic")
        entry["failing"] = name in failed
    return sorted(sources.values(), key=lambda e: e["name"].lower())


def catalog(
    config: dict, digest: str, rpms: list[dict], *, image: str, root: Path
) -> dict:
    labels = (config.get("config") or {}).get("Labels") or {}
    try:
        state = json.loads(labels.get(STATE_LABEL, "{}"))
    except json.JSONDecodeError:
        state = {}
    failed = set((state.get("failed") or {}).keys())
    packages = group(rpms, root, failed)
    return {
        "schema": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "image": {
            "ref": image,
            "digest": digest,
            "created": config.get("created", ""),
            "revision": labels.get("org.opencontainers.image.revision", ""),
            "run": labels.get("org.projectbluefin.factory.run", ""),
        },
        "totals": {
            "sources": len(packages),
            "rpms": len(rpms),
            "size": sum(r["size"] for r in rpms),
            "installed": sum(r["installed"] for r in rpms),
            "failing": sorted(failed),
        },
        "packages": packages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--image",
        default="projectbluefin/utah-packages:latest",
        help="OWNER/NAME:TAG on ghcr.io",
    )
    parser.add_argument(
        "--layer",
        type=Path,
        help="read a saved repodata layer instead of the registry (needs --config)",
    )
    parser.add_argument("--config", type=Path, help="saved image config JSON")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    repository, _, tag = args.image.rpartition(":")
    if not repository or "/" in tag:
        repository, tag = args.image, "latest"
    if args.layer:
        if not args.config:
            parser.error("--layer needs --config")
        config = json.loads(args.config.read_text())
        digest, blob = "", args.layer.read_bytes()
    else:
        config, digest, blob = fetch_image(repository, tag)

    rpms = parse_primary(primary_from_layer(blob))
    payload = catalog(
        config, digest, rpms, image=f"{REGISTRY}/{repository}:{tag}", root=ROOT
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    totals = payload["totals"]
    print(
        f"wrote {args.output}: {totals['sources']} source packages, "
        f"{totals['rpms']} RPMs from {payload['image']['ref']}@{digest or '?'}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
