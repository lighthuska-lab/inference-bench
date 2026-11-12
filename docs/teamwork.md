# First teammate contribution: CSV export

The runner and JSON reports are the foundation. The teammate owns CSV export,
which lets users analyze outcomes in spreadsheets without writing a converter.

## What the owner does

1. The first contributor is [jeffwalsh728-tech](https://github.com/jeffwalsh728-tech).
   For direct branch access, the owner invites them under Settings > Collaborators.
   They must accept the invitation before pushing a branch. They can instead fork
   the repository and submit a PR without collaborator access.
2. Agree that the teammate owns the CSV issue. Do not implement their feature
   in parallel unless they ask for help.
3. Review their PR, reproduce its tests, and discuss findings. Ask them to review
   a separate meaningful change in the same way.

## What the teammate does

1. Clone the repository and run its offline tests using the README.
2. Create `feature/csv-export` and add an optional `--csv-output PATH` argument.
   JSON stdout and `--output` must keep working as they do now.
3. Use Python's standard `csv` module and write UTF-8 with `newline=""`. Export
   one row per measured request, in `request_id` order. Columns are
   `request_id,latency_ms,status_code,error,completion_tokens`. Warmups do not
   belong in this file. Missing values are empty fields, not the string `None`.
4. Add tests for successful, failed, and missing-usage rows, real CSV parsing,
   unwritable output, and simultaneous JSON/CSV output. Preserve existing exit
   codes. Do not include prompts, keys, generated text, or server error bodies.
5. Document a runnable command and open a PR with the issue link and actual
   checks run. Keep authorship on their own commits. Mark co-authors only for
   work created together, with agreement from those people.
6. Address review feedback, then ask for another review. Do not automatically
   approve another person's work in exchange for an achievement.

## Definition of done

The feature passes existing and new tests, lint, formatting, package builds,
and CI. The README example works against the local mock endpoint. A reviewer
has inspected the diff and verified the behavior. No particular GitHub badge
or number of followers is guaranteed by this contribution.
