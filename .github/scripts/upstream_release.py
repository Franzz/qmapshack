#!/usr/bin/env python3
"""Synchronize the fork and publish numbered Windows builds of upstream releases."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import quote


UPSTREAM = "Maproom/qmapshack"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def api(path):
    return json.loads(run("gh", "api", path))


def releases(repository):
    pages = json.loads(run(
        "gh", "api", "--paginate", "--slurp",
        f"repos/{repository}/releases?per_page=100",
    ))
    return [release for page in pages for release in page]


def validate_version(version):
    # The upstream tag also becomes part of a Windows filename and an Actions output.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
        raise ValueError(f"Unsupported upstream release tag: {version!r}")
    run("git", "check-ref-format", f"refs/tags/{version}-build1")
    return version


def outputs(**values):
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        for name, value in values.items():
            output.write(f"{name}={value}\n")


def summary(message):
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(message + "\n")


def installer_name(release_tag):
    return f"qmapshack-win64-{release_tag}-setup.exe"


def has_installer(release, upstream_tag):
    tag = release["tag_name"]
    if release["draft"] or release["prerelease"]:
        return False
    if not re.fullmatch(re.escape(upstream_tag) + r"-build[1-9][0-9]*", tag):
        return False
    return any(
        asset["name"] == installer_name(tag)
        and asset["state"] == "uploaded" and asset["size"] > 0
        for asset in release["assets"]
    )


def prepare(repository, rebuild=False):
    release = api(f"repos/{UPSTREAM}/releases/latest")
    upstream_tag = validate_version(release["tag_name"])
    if not rebuild and any(has_installer(item, upstream_tag) for item in releases(repository)):
        outputs(should_build="false")
        summary(f"An installer for upstream release {upstream_tag} is already published; skipping.")
        return

    run("git", "config", "user.name", "github-actions[bot]")
    run("git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com")
    run("git", "fetch", "--no-tags", "origin",
        "+refs/heads/master:refs/remotes/origin/master",
        "+refs/heads/build:refs/remotes/origin/build")
    run("git", "fetch", "--no-tags", f"https://github.com/{UPSTREAM}.git",
        "+refs/heads/master:refs/remotes/upstream/master",
        f"+refs/tags/{upstream_tag}:refs/remotes/upstream/release")
    upstream_sha = run("git", "rev-parse", "refs/remotes/upstream/release^{commit}")
    master_sha = run("git", "rev-parse", "refs/remotes/upstream/master")
    run("git", "merge-base", "--is-ancestor", upstream_sha, master_sha)

    run("git", "switch", "-C", "master", "refs/remotes/origin/master")
    run("git", "merge", "--ff-only", "refs/remotes/upstream/master")
    if run("git", "rev-parse", "HEAD") != master_sha:
        raise RuntimeError("Fork master has its own commits; it must remain an upstream mirror.")
    # Update master first, even if merging it into build subsequently conflicts.
    run("git", "push", "origin", "refs/heads/master:refs/heads/master")
    run("git", "switch", "-C", "build", "refs/remotes/origin/build")
    try:
        run("git", "merge", "--no-edit", "refs/heads/master")
    except subprocess.CalledProcessError:
        conflicts = run("git", "diff", "--name-only", "--diff-filter=U")
        run("git", "merge", "--abort")
        summary("Merging master into build failed. No Windows build or release was started.\n\n"
                + "Conflicting files:\n\n```\n" + conflicts + "\n```")
        raise
    run("git", "push", "origin", "refs/heads/build:refs/heads/build")
    build_sha = run("git", "rev-parse", "HEAD")
    outputs(should_build="true", upstream_tag=upstream_tag,
            upstream_url=release["html_url"], upstream_sha=upstream_sha,
            master_sha=master_sha, build_sha=build_sha)
    summary(f"Ready to build {upstream_tag} from build commit `{build_sha}` "
            f"after synchronizing upstream master `{master_sha}`.")


def reserve(upstream_tag, build_sha):
    validate_version(upstream_tag)
    if run("git", "rev-parse", "HEAD") != build_sha:
        raise RuntimeError("Checkout does not match the prepared build commit.")
    pattern = re.compile(r"refs/tags/" + re.escape(upstream_tag) + r"-build([1-9][0-9]*)")
    numbers = []
    for line in run("git", "ls-remote", "--tags", "origin").splitlines():
        match = pattern.fullmatch(line.split("\t", 1)[1])
        if match:
            numbers.append(int(match[1]))
    number = max(numbers, default=0) + 1
    tag = f"{upstream_tag}-build{number}"
    # Reserve before compiling: failed builds and rerun attempts also consume a number.
    # A tag alone is not a published release and will not suppress the next retry.
    run("git", "tag", tag, build_sha)
    run("git", "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}")
    outputs(release_tag=tag, build_number=number)
    summary(f"Reserved {tag} for build commit `{build_sha}`.")


def publish(repository, upstream_tag, build_sha, release_tag, asset):
    validate_version(upstream_tag)
    if not re.fullmatch(re.escape(upstream_tag) + r"-build[1-9][0-9]*", release_tag):
        raise ValueError("Release tag does not match the upstream version.")
    if Path(asset).name != installer_name(release_tag) or Path(asset).stat().st_size == 0:
        raise ValueError("The Windows installer is missing, empty, or incorrectly named.")
    if run("git", "rev-parse", f"refs/tags/{release_tag}^{{commit}}") != build_sha:
        raise RuntimeError("Release tag does not point to the built commit.")
    run_url = (f"{os.environ['GITHUB_SERVER_URL']}/{repository}/actions/runs/"
               f"{os.environ['GITHUB_RUN_ID']}")
    notes = (
        f"Windows installer for QMapShack {upstream_tag}.\n\n"
        f"Upstream release: {os.environ['UPSTREAM_URL']}\n\n"
        f"Upstream release commit: `{os.environ['UPSTREAM_SHA']}`\n"
        f"Upstream master commit: `{os.environ['MASTER_SHA']}`\n"
        f"Build commit: `{build_sha}`\n\n"
        f"Built by [GitHub Actions]({run_url}) "
        f"(attempt {os.environ['GITHUB_RUN_ATTEMPT']}).\n"
    )
    with tempfile.TemporaryDirectory() as directory:
        notes_path = Path(directory) / "release-notes.md"
        notes_path.write_text(notes, encoding="utf-8")
        # Publish only after the installer is attached. A failed upload leaves a draft,
        # which does not count as a completed release on the next scheduled check.
        run("gh", "release", "create", release_tag, "--repo", repository,
            "--verify-tag", "--draft", "--title", release_tag,
            "--notes-file", str(notes_path))
        run("gh", "release", "upload", release_tag, asset, "--repo", repository)
        run("gh", "release", "edit", release_tag, "--repo", repository,
            "--draft=false", "--latest")
    summary(f"Published [{release_tag}]({os.environ['GITHUB_SERVER_URL']}/{repository}"
            f"/releases/tag/{quote(release_tag, safe='')}) with `{Path(asset).name}`.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("prepare", "reserve", "publish"))
    operation = parser.parse_args().operation
    repository = os.environ["GITHUB_REPOSITORY"]
    if operation == "prepare":
        prepare(repository, rebuild=os.environ.get("REBUILD", "false").lower() == "true")
    elif operation == "reserve":
        reserve(os.environ["UPSTREAM_TAG"], os.environ["BUILD_SHA"])
    else:
        publish(repository, os.environ["UPSTREAM_TAG"], os.environ["BUILD_SHA"],
                os.environ["RELEASE_TAG"], os.environ["INSTALLER_NAME"])


if __name__ == "__main__":
    main()
