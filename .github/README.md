# Windows releases in the fork

The `build` branch contains the Windows workflow and packaging changes. Keep the
fork's `master` branch as an exact mirror of `Maproom/qmapshack:master`.

Whenever possible, implement fork-specific changes in new files that do not
come from upstream. Keep changes to upstream-maintained files to a minimum to
reduce merge conflicts when synchronizing future releases.

Set the fork's default branch to `build` and enable GitHub Actions for the fork.
GitHub schedules workflows only from the default branch. The workflow uses the
repository's `GITHUB_TOKEN` with `contents: write`; it does not need a personal
access token. Branch rules must allow GitHub Actions to push to `master` and
`build` and create release tags.

GitHub [automatically disables scheduled workflows in public repositories after
60 days without repository activity](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
If this happens between upstream releases, re-enable **Build Windows** in Actions.

## Scheduled checks

`.github/workflows/windows.yml` checks the latest published, non-prerelease
upstream release every six hours, at 00:17, 06:17, 12:17, and 18:17 UTC. GitHub may
delay scheduled runs. If that upstream version already has a published fork
release with its installer attached, the run exits without a Windows build.
The first check builds the current upstream release if the fork has no installer
for it yet.

When a build is needed, the workflow:

1. Fast-forwards the fork's `master` to the upstream `master` and pushes it.
2. Merges that `master` into `build` and pushes the result. A conflict aborts the
   merge and fails the run; no Windows build or release follows. The updated
   `master` stays in place. Resolve conflicts on `build`, then run the workflow
   again or wait for the next check.
3. Checks out the exact merged commit on Windows and reserves its next build
   number with a Git tag, such as `V_1.21.1-build1`.
4. Builds, checks the staged runtime, smoke tests the applications, and packages
   the Windows installer. The installer is also retained as an Actions artifact.
5. Creates a draft release named after the reserved tag, uploads
   `qmapshack-win64-V_1.21.1-build1-setup.exe`, and publishes the release only
   after the upload succeeds.

As requested, the source is the upstream **master tip**, which may have advanced
beyond the release tag by the time the check runs. Release notes record the
upstream release commit, upstream master commit, and actual build commit.

All runs share a concurrency group so merges and build numbers are serialized.
Build numbers start at 1 for each upstream tag and increase on each build
attempt, including failures and reruns. Failed attempts leave a reserved Git tag
but no published release. This lets the next check retry with a new number.
Do not delete these tags if you want to preserve the numbering history.

## Direct pushes and manual rebuilds

Pushing commits to `build` automatically starts a new build, even when the
latest upstream version already has an installer. This lets packaging and
workflow fixes produce the next numbered release for the same upstream version.

In Actions, select **Build Windows**, then **Run workflow** on `build`. Leave
`rebuild` unchecked to check for an unbuilt upstream release immediately. Check
it to rebuild the latest upstream release even when an installer already
exists; the build uses the next number for that version.

The merge and Windows build run as dependent jobs in the same workflow. They
do not rely on a push by `GITHUB_TOKEN` triggering another workflow. Automated
merge pushes use `GITHUB_TOKEN`, so they do not trigger a second build run.

## Email and GitHub notifications

Use GitHub's built-in notifications to receive failures and successful releases
at the account's configured **Default notifications email**, while keeping
checks that find no new upstream release silent:

| Result | Notification |
| --- | --- |
| Merge conflict or failed build, validation, packaging, or publication | Failed Actions workflow |
| Successful build with installer published | New release |
| No new upstream release and no build | None |

Enable delivery once in your personal [notification settings](https://github.com/settings/notifications):

1. Under **System > Actions**, enable **Email** and **On GitHub**, and enable
   **Only notify for failed workflows**, then save the settings.
2. Under **Subscriptions > Watching**, enable **Email** and **On GitHub** for
   notifications from watched repositories.
3. In [Franzz/qmapshack](https://github.com/Franzz/qmapshack), select
   **Watch > Custom > Releases**, then apply the selection. Every successful
   build publishes a release with the installer attached, which supplies the
   success notification.
4. Confirm that **Default notifications email** is the address you want to use.

These are personal account settings; the workflow does not enable them or read
the notification email address. No mail-server credentials are required. See
GitHub's [Actions notification setup](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications)
and [release notifications](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases).

Push and manual-run notifications go to the user who triggered the run.
Scheduled-run notifications go to the user who created or last edited the cron
schedule, or who re-enabled the scheduled workflow. Make those changes using
your own GitHub account so the scheduled notifications reach you.

The Actions failure filter is an account setting and also applies to other
workflows you trigger. The release subscription is specific to this repository.

## Local verification

Run `python3 -m unittest discover -s .github/scripts -v`. Tests use temporary Git
repositories to check the mirror and merge behavior, conflict handling, retries,
build numbering, and release publication order. They do not build the Windows
application or call GitHub.
