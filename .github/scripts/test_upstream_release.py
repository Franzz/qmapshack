"""Exercise synchronization and numbering with real, isolated Git repositories."""

import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import upstream_release as release


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.upstream = self.root / "upstream.git"
        self.origin = self.root / "origin.git"
        self.seed = self.root / "seed"
        self.worker = self.root / "worker"
        for remote in (self.upstream, self.origin):
            self.git("init", "--bare", str(remote), cwd=self.root)
        self.git("init", "--initial-branch=master", str(self.seed), cwd=self.root)
        self.git("config", "user.name", "Test", cwd=self.seed)
        self.git("config", "user.email", "test@example.invalid", cwd=self.seed)
        (self.seed / "app.txt").write_text("original\n")
        self.commit("Initial upstream release")
        self.tag = "V_1.21.1"
        self.git("tag", self.tag, cwd=self.seed)
        self.git("push", str(self.upstream), "master", "--tags", cwd=self.seed)
        self.git("push", str(self.origin), "master", cwd=self.seed)
        self.git("switch", "-c", "build", cwd=self.seed)
        (self.seed / "installer.txt").write_text("Build customizations\n")
        self.commit("Add Windows packaging")
        self.git("push", str(self.origin), "build", cwd=self.seed)
        self.git("clone", "--branch", "build", str(self.origin), str(self.worker), cwd=self.root)
        self.git("config", f"url.{self.upstream}.insteadOf",
                 f"https://github.com/{release.UPSTREAM}.git", cwd=self.worker)

        previous = Path.cwd()
        os.chdir(self.worker)
        self.addCleanup(os.chdir, previous)
        self.output = self.root / "outputs"
        env = {
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_STEP_SUMMARY": str(self.root / "summary"),
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "1234",
            "GITHUB_RUN_ATTEMPT": "1",
            "UPSTREAM_URL": "https://github.com/Maproom/qmapshack/releases/tag/V_1.21.1",
            "UPSTREAM_SHA": "upstream-release-sha",
            "MASTER_SHA": "upstream-master-sha",
        }
        environment = patch.dict(os.environ, env)
        environment.start()
        self.addCleanup(environment.stop)
        self.fork_releases = []
        api = patch.object(release, "api", side_effect=lambda _: {
            "tag_name": self.tag,
            "html_url": f"https://github.com/{release.UPSTREAM}/releases/tag/{self.tag}",
        })
        api.start()
        self.addCleanup(api.stop)
        releases = patch.object(release, "releases", side_effect=lambda _: self.fork_releases)
        releases.start()
        self.addCleanup(releases.stop)
        stdout = contextlib.redirect_stdout(io.StringIO())
        stdout.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)

    @staticmethod
    def git(*args, cwd=None):
        return subprocess.check_output(
            ("git", *args), cwd=cwd, text=True, stderr=subprocess.PIPE,
        ).strip()

    def commit(self, message):
        self.git("add", ".", cwd=self.seed)
        self.git("commit", "-m", message, cwd=self.seed)

    def new_release(self):
        self.git("switch", "master", cwd=self.seed)
        (self.seed / "app.txt").write_text("new upstream version\n")
        self.commit("New upstream release")
        self.tag = "V_1.22.0"
        self.git("tag", self.tag, cwd=self.seed)
        self.git("push", str(self.upstream), "master", "--tags", cwd=self.seed)
        return self.git("rev-parse", "HEAD", cwd=self.seed)

    def values(self):
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def remote_sha(self, branch):
        return self.git("rev-parse", f"refs/heads/{branch}", cwd=self.origin)

    def published(self, **changes):
        tag = f"{self.tag}-build1"
        return dict({
            "tag_name": tag, "draft": False, "prerelease": False,
            "assets": [{"name": release.installer_name(tag), "state": "uploaded", "size": 100}],
        }, **changes)

    def test_initial_release_builds_without_losing_customizations(self):
        original_build = self.remote_sha("build")
        release.prepare("test/fork")
        self.assertEqual(self.values()["should_build"], "true")
        self.assertEqual(self.values()["build_sha"], original_build)
        self.assertEqual((self.worker / "installer.txt").read_text(), "Build customizations\n")
        self.assertEqual(self.remote_sha("master"), self.values()["master_sha"])

    def test_new_release_updates_master_then_merges_into_build(self):
        old_build = self.remote_sha("build")
        upstream_sha = self.new_release()
        release.prepare("test/fork")
        self.assertEqual(self.remote_sha("master"), upstream_sha)
        self.assertEqual(self.remote_sha("build"), self.values()["build_sha"])
        self.assertEqual(self.git("show", "-s", "--format=%P", "HEAD").split(),
                         [old_build, upstream_sha])
        self.assertTrue((self.worker / "installer.txt").exists())
        self.assertEqual((self.worker / "app.txt").read_text(), "new upstream version\n")

    def test_conflict_updates_only_master_and_blocks_build(self):
        (self.seed / "app.txt").write_text("conflicting build customization\n")
        self.commit("Change the same line on build")
        self.git("push", str(self.origin), "build", cwd=self.seed)
        old_build = self.remote_sha("build")
        upstream_sha = self.new_release()
        with self.assertRaises(subprocess.CalledProcessError):
            release.prepare("test/fork")
        self.assertEqual(self.remote_sha("master"), upstream_sha)
        self.assertEqual(self.remote_sha("build"), old_build)
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertFalse(self.output.exists())
        self.assertIn("app.txt", (self.root / "summary").read_text())

    def test_master_with_own_commits_is_rejected(self):
        self.git("switch", "master", cwd=self.seed)
        (self.seed / "fork-only.txt").write_text("not an upstream mirror\n")
        self.commit("Accidental fork master change")
        self.git("push", str(self.origin), "master", cwd=self.seed)
        old_build = self.remote_sha("build")
        with self.assertRaisesRegex(RuntimeError, "upstream mirror"):
            release.prepare("test/fork")
        self.assertEqual(self.remote_sha("build"), old_build)
        self.assertFalse(self.output.exists())

    def test_complete_release_skips_and_manual_rebuild_overrides_it(self):
        self.fork_releases = [self.published()]
        release.prepare("test/fork")
        self.assertEqual(self.values()["should_build"], "false")
        release.prepare("test/fork", rebuild=True)
        self.assertEqual(self.values()["should_build"], "true")

    def test_drafts_incomplete_assets_and_other_versions_do_not_suppress_retry(self):
        for item in (
            self.published(draft=True), self.published(prerelease=True),
            self.published(assets=[]), self.published(tag_name="V_1.21.10-build1"),
            self.published(assets=[{"name": "installer.exe", "state": "uploaded", "size": 100}]),
            self.published(assets=[{"name": release.installer_name(f"{self.tag}-build1"),
                                    "state": "uploaded", "size": 0}]),
        ):
            with self.subTest(release=item):
                self.assertFalse(release.has_installer(item, self.tag))
        self.fork_releases = [self.published(draft=True)]
        release.prepare("test/fork")
        self.assertEqual(self.values()["should_build"], "true")

    def test_numbering_includes_failed_builds_reruns_and_resets_for_new_version(self):
        for tag in (f"{self.tag}-build1", f"{self.tag}-build7", "V_1x21x1-build99"):
            self.git("tag", tag, cwd=self.seed)
        self.git("tag", "-a", f"{self.tag}-build8", "-m", "Failed build", cwd=self.seed)
        self.git("push", str(self.origin), "--tags", cwd=self.seed)
        sha = self.git("rev-parse", "HEAD")
        release.reserve(self.tag, sha)
        self.assertEqual(self.values()["release_tag"], f"{self.tag}-build9")
        self.assertEqual(self.git("rev-parse", f"refs/tags/{self.tag}-build9", cwd=self.origin), sha)
        release.reserve(self.tag, sha)
        self.assertEqual(self.values()["build_number"], "10")
        release.reserve("V_1.22.0", sha)
        self.assertEqual(self.values()["release_tag"], "V_1.22.0-build1")

    def test_wrong_checkout_does_not_reserve_a_number(self):
        with self.assertRaisesRegex(RuntimeError, "prepared build commit"):
            release.reserve(self.tag, "wrong-commit")
        self.assertFalse(self.output.exists())

    def publication(self, fail_upload=False):
        sha = self.git("rev-parse", "HEAD")
        release.reserve(self.tag, sha)
        tag = self.values()["release_tag"]
        asset = release.installer_name(tag)
        Path(asset).write_bytes(b"installer")
        original_run = release.run
        calls = []

        def fake_gh(*args):
            if args[0] != "gh":
                return original_run(*args)
            calls.append(args)
            if args[2] == "create":
                notes = Path(args[args.index("--notes-file") + 1]).read_text()
                self.assertIn(sha, notes)
                self.assertIn("upstream-master-sha", notes)
            if fail_upload and args[2] == "upload":
                raise subprocess.CalledProcessError(1, args)
            return ""

        with patch.object(release, "run", side_effect=fake_gh):
            if fail_upload:
                with self.assertRaises(subprocess.CalledProcessError):
                    release.publish("test/fork", self.tag, sha, tag, asset)
            else:
                release.publish("test/fork", self.tag, sha, tag, asset)
        return calls

    def test_installer_is_uploaded_to_draft_before_publishing(self):
        calls = self.publication()
        self.assertEqual([args[2] for args in calls], ["create", "upload", "edit"])
        self.assertIn("--draft", calls[0])
        self.assertIn("--verify-tag", calls[0])
        self.assertIn("--draft=false", calls[2])

    def test_failed_upload_does_not_publish_release(self):
        self.assertEqual([args[2] for args in self.publication(fail_upload=True)],
                         ["create", "upload"])


if __name__ == "__main__":
    unittest.main()
