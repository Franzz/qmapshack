#!/usr/bin/env python3
"""Fetch one pinned GISInternals SDK and stage its matching runtime dependency closure."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request
import zipfile


LOCK = Path(__file__).resolve().parents[1] / "raster" / "gisinternals.lock.json"


def verified_download(url, destination, digest):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    actual = None
    if destination.exists():
        with destination.open("rb") as source:
            actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != digest:
        temporary = destination.with_suffix(destination.suffix + ".partial")
        try:
            with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target)
            with temporary.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            if actual != digest:
                raise RuntimeError(f"SHA256 mismatch for {url}: {actual}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def extract(archive_path, destination):
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename.replace("\\", "/")).resolve()
            if not target.is_relative_to(destination):
                raise ValueError(f"Archive member escapes destination: {member.filename}")
        archive.extractall(destination)


def fetch(root, cache, lock):
    for archive in lock["archives"]:
        path = verified_download(archive["url"], cache / archive["name"], archive["sha256"])
        extract(path, root)
    for name in ("include/gdal.h", "include/proj9/proj.h", "include/jpeglib.h",
                 "include/mysql.h", "include/mysql_version.h",
                 "lib/gdal_i.lib", "lib/proj9.lib", "lib/libjpeg.lib", "lib/libmysql.lib",
                 "bin/gdal.dll", "bin/proj_9.dll", "bin/libmysql.dll", "bin/proj9/share/proj.db"):
        if not (root / name).is_file():
            raise RuntimeError(f"GISInternals SDK is incomplete: {name}")
    for name in lock["plugins"]:
        if not (root / "bin/gdal/plugins" / name).is_file():
            raise RuntimeError(f"Required GISInternals plugin is missing: {name}")
    for name in lock["required_licenses"]:
        if not (root / name).is_file():
            raise RuntimeError(f"Required vendor license is missing: {name}")
    print(f"Verified {lock['package']} ({lock['compiler']}).")


def dependencies(module):
    result = subprocess.run(["dumpbin", "/nologo", "/dependents", str(module)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    # Includes both ordinary and delay-load imports reported by dumpbin.
    return re.findall(r"(?im)^\s+([A-Za-z0-9_.+-]+\.dll)\s*$", result.stdout)


def stage(root, destination, lock):
    destination.mkdir(parents=True, exist_ok=True)
    plugin_dir = destination / "gdalplugins"
    plugin_dir.mkdir(exist_ok=True)
    modules = {path.name.lower(): path for path in (root / "bin").glob("*.dll")}
    system = Path(os.environ["SystemRoot"]) / "System32"
    roots = [(root / "bin/gdal.dll", destination / "gdal.dll"),
             (root / "bin/proj_9.dll", destination / "proj_9.dll"),
             (root / "bin/libmysql.dll", destination / "libmysql.dll")]
    for subdirectory in ("bin/gdal/apps", "bin/proj9/apps"):
        roots.extend((path, destination / path.name) for path in (root / subdirectory).glob("*.exe"))
    roots.extend((root / "bin/gdal/plugins" / name, plugin_dir / name) for name in lock["plugins"])
    # qmt_map2jnx links libjpeg directly. Include its DLL even if GDAL does not import it.
    roots.extend((path, destination / path.name) for path in (root / "bin").glob("*.dll")
                 if re.fullmatch(r"(?:lib)?jpeg\d*\.dll", path.name, re.IGNORECASE))
    seen = set()
    copied = []
    while roots:
        source, target = roots.pop()
        if target.name.lower() in seen:
            continue
        seen.add(target.name.lower())
        if not source.is_file():
            raise RuntimeError(f"Required runtime module is missing: {source}")
        shutil.copy2(source, target)
        copied.append(str(target.relative_to(destination)))
        for name in dependencies(source):
            # Use the installed official VC++ redistributable instead of SDK copies.
            if name.lower().startswith(("api-ms-", "ext-ms-", "msvcp", "vcruntime", "concrt")):
                continue
            if name.lower() in modules:
                dependency = modules[name.lower()]
                roots.append((dependency, destination / dependency.name))
            elif not (system / name).is_file():
                raise RuntimeError(f"Unresolved dependency of {source.name}: {name}")
    shutil.copytree(root / "bin/gdal-data", destination / "data", dirs_exist_ok=True)
    shutil.copytree(root / "bin/proj9/share", destination / "share/proj", dirs_exist_ok=True)
    certificate = root / "bin/curl-ca-bundle.crt"
    if certificate.is_file():
        shutil.copy2(certificate, destination / certificate.name)
    licenses = destination / "licenses/gisinternals"
    licenses.mkdir(parents=True, exist_ok=True)
    for pattern in ("*.rtf", "*license*.txt", "*License*.txt"):
        for path in root.glob(pattern):
            shutil.copy2(path, licenses / path.name)
    shutil.copy2(LOCK, licenses / "gisinternals.lock.json")
    (licenses / "runtime-modules.json").write_text(json.dumps(sorted(copied), indent=2) + "\n")
    print(f"Staged {len(copied)} GISInternals modules and vendor license files.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "stage"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--dist", type=Path)
    args = parser.parse_args()
    lock = json.loads(LOCK.read_text())
    if args.operation == "fetch":
        fetch(args.root.resolve(), args.cache or args.root / "downloads", lock)
    else:
        if args.dist is None:
            parser.error("stage requires --dist")
        stage(args.root.resolve(), args.dist.resolve(), lock)


if __name__ == "__main__":
    main()
