#!/usr/bin/env python3
"""Build QMYSQL for the installed Qt kit and the bundled GISInternals MySQL client."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess

from gisinternals import extract, verified_download


LOCK = Path(__file__).resolve().parents[1] / "raster" / "qt-mysql.lock.json"


def build(qt_root, sdk_root, work, cache, destination):
    lock = json.loads(LOCK.read_text())
    version = subprocess.check_output(
        [str(qt_root / "bin/qmake.exe"), "-query", "QT_VERSION"], text=True
    ).strip()
    if version != lock["qt_version"]:
        raise RuntimeError(f"QMYSQL sources require Qt {lock['qt_version']}, found {version}")

    toolchain = qt_root / "lib/cmake/Qt6/qt.toolchain.cmake"
    for path in (toolchain, sdk_root / "include/mysql.h", sdk_root / "include/mysql_version.h",
                 sdk_root / "lib/libmysql.lib", sdk_root / "bin/libmysql.dll"):
        if not path.is_file():
            raise RuntimeError(f"Required QMYSQL build dependency is missing: {path}")

    source = lock["source"]
    archive = verified_download(source["url"], cache / source["name"], source["sha256"])
    extract(archive, work / "source")
    qtbase = work / "source" / f"qtbase-{lock['qtbase_revision']}"
    build_dir = work / "build"
    # Equivalent to qt-cmake: use this installed kit's toolchain and private headers.
    # MySQL_ROOT also disables pkg-config discovery of a different MySQL client.
    subprocess.run([
        "cmake", "-S", str(qtbase / "src/plugins/sqldrivers"), "-B", str(build_dir),
        "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_TOOLCHAIN_FILE={toolchain}", f"-DCMAKE_PREFIX_PATH={qt_root}",
        f"-DMySQL_ROOT={sdk_root}", f"-DMySQL_INCLUDE_DIR={sdk_root / 'include'}",
        f"-DMySQL_LIBRARY={sdk_root / 'lib/libmysql.lib'}",
        "-DFEATURE_sql_mysql=ON", "-DFEATURE_sql_sqlite=OFF",
        "-DQT_BUILD_TESTS=OFF", "-DQT_BUILD_EXAMPLES=OFF",
    ], check=True)
    subprocess.run([
        "cmake", "--build", str(build_dir), "--config", "Release",
        "--target", "QMYSQLDriverPlugin", "--parallel",
    ], check=True)

    plugins = list(build_dir.rglob("qsqlmysql.dll"))
    if len(plugins) != 1:
        raise RuntimeError(f"Expected one built qsqlmysql.dll, found: {plugins}")
    plugin_dir = destination / "sqldrivers"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plugins[0], plugin_dir / "qsqlmysql.dll")

    licenses = destination / "licenses/qt-mysql"
    shutil.copytree(qtbase / "LICENSES", licenses, dirs_exist_ok=True)
    shutil.copy2(LOCK, licenses / LOCK.name)
    print(f"Staged QMYSQL from Qt {version}, linked to {sdk_root / 'lib/libmysql.lib'}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-root", type=Path, required=True)
    parser.add_argument("--sdk-root", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--dist", type=Path, required=True)
    args = parser.parse_args()
    build(args.qt_root.resolve(), args.sdk_root.resolve(), args.work.resolve(),
          args.cache.resolve(), args.dist.resolve())


if __name__ == "__main__":
    main()
