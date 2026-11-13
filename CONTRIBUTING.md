# Contributing

Start with an existing issue or describe a reproducible problem before making a
large change. Keep each pull request focused on one behavior and include tests
that fail without the fix. Do not split a single trivial change into multiple PRs.

Use a branch such as `feature/csv-export`. Run the checks in the README, then open
a PR explaining the problem, implementation, test results, and limitations. Do not
commit API keys, real prompts, private endpoint names, or unreviewed result files.

Reviewers should read the diff, run relevant tests, and provide concrete feedback.
An approval should mean the reviewer actually checked the change. Authors should
address feedback before requesting another review.

Automation follows the same review requirement. Dependabot opens real dependency
updates. Eligible updates can be queued for auto-merge, but a maintainer must
review them and all required CI jobs must pass. New commits invalidate prior
approvals. See [the pipeline guide](docs/automation.md).

Keep each person's author identity on their commits. Add a `Co-authored-by`
trailer only when the named person actually helped create that commit and agrees
to the attribution. GitHub achievements are not a reason to invent work, credit,
reviews, issues, stars, or accounts.

Contributions are made under the repository's MIT license. There is no CLA.
