# Maintenance pipeline

This pipeline automates maintenance rather than creating activity for its own
sake. It does not create empty commits, generate arbitrary code, approve itself,
buy stars, follow accounts, or promise followers or GitHub achievements.

## What happens automatically

1. CI runs tests, lint, formatting, package builds, and installed-entrypoint checks
   on Python 3.11–3.14 for PRs and main pushes. It also runs weekly on Monday at
   09:23 UTC (03:23 CST or 04:23 CDT in Chicago). A scheduled check does not write
   commits or open PRs when nothing changed.
2. Dependabot checks Python development/build dependencies and pinned GitHub
   Actions weekly, Monday at 10:00 America/Chicago. It creates commits and PRs only
   for available updates. Non-major updates are grouped to limit review noise.
3. The auto-merge workflow recognizes same-repository Dependabot PRs targeting
   main. For known patch/minor updates it queues GitHub auto-merge. GitHub waits
   for the required checks, branch freshness, and a current approving review.
   Major or unclassified updates require a maintainer to manage merging.
4. An intentional stable version tag triggers the complete CI suite again. A
   release is published only if the tagged commit is on main and the tag, package
   metadata, and CLI version match. It uploads the wheel and source distribution
   to a GitHub release. It does not publish to PyPI or move an existing tag.

Dependabot commits are attributed to Dependabot, not falsely credited to the
maintainer. Normal feature development still starts with a real issue and review.

## Repository gates

The main branch must require these status checks, all from GitHub Actions:

- `Python 3.11`
- `Python 3.12`
- `Python 3.13`
- `Python 3.14`

Require the branch to be up to date, one approving review, stale-approval
dismissal, and an approver other than the latest pusher. Apply the requirements
to administrators too. Disable force pushes and branch deletion. Enable the
repository's Allow auto-merge setting. These are GitHub repository settings,
not settings that a workflow file can enforce by itself.

These gates also apply to existing feature PRs. A previous changes-requested
review must be addressed and re-reviewed. Do not dismiss it merely to let a bot
merge. If a branch becomes outdated, update it, rerun CI, and refresh any approval
GitHub marks stale.

The bot never checks out or executes PR code in its merge-enabling job. It uses
the short-lived `GITHUB_TOKEN`, with write permissions only in that metadata job.
The CI workflow has read-only permissions. No personal token or AI API key is
needed. There is no merge queue configured for this personal repository.

## Maintainer and Jeff's roles

Review the actual dependency diff, release notes, and CI results. Do not approve
an update merely because the bot opened it. GitHub completes the queued merge
once all gates pass. PR authors cannot supply their own required approval.

For an ordinary feature PR, enable auto-merge in GitHub after it is ready for
review, or use `gh pr merge --auto --merge PR_NUMBER`. The workflow only queues
Dependabot updates automatically. It does not manufacture feature PRs.

To release a new version, update both `pyproject.toml` and
`src/inference_bench/__init__.py` in a reviewed PR. After it merges and main is
green, tag that tested commit. For example, when both versions are `0.2.0`:

```bash
git switch main
git pull --ff-only
git tag v0.2.0
git push origin v0.2.0
```

Only use this example after the version PR is merged. Existing preview v0.1.0 is
not republished. Prerelease tags are not published automatically. A failed run
does not justify bypassing validation. Inspect the failure and rerun the workflow
after correcting its cause.

## Activation and limits

The configuration starts working after its PR is reviewed and merged into main.
The first real Dependabot update and next real release tag are the end-to-end
activation checks. Those cannot be simulated by opening an empty update PR or
publishing a fake version. Workflows may be delayed by GitHub's scheduler, and
public-repository schedules can be disabled after extended inactivity.

To pause scheduled maintenance, disable the relevant Actions workflow and adjust
the Dependabot configuration through a reviewed PR. Keep the main-branch gates
enabled for manual work. This pipeline improves consistency, not account metrics.

[GitHub's Dependabot automation guide](https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/automate-dependabot-with-actions)
describes the metadata/auto-merge mechanism. The workflow deliberately does not
use the guide's auto-approval example.
