# apply_pr (`sastre`)

`apply_pr` deploys GitHub pull requests to an existing Git checkout. Its
`sastre` command can apply every commit as a patch with `git am`, or apply the
pull request as a single diff. It also records GitHub deployment statuses and
provides commands for inspecting deployments and creating changelogs.

The tool is intended for controlled deployments to local or remote servers.
It does not clone or provision the target repository: the checkout must
already exist below `--src` and must be in the state expected by your
deployment process.

## Requirements

- Python 2.7 or Python 3.11
- Git on the machine running `sastre` and on deployment targets
- SSH access for remote deployments
- A GitHub account with access to the repositories being deployed

The supported Python versions are the versions exercised by CI. Python 2.7
support is retained for legacy deployment environments.

## Installation

Install the published package from PyPI:

```console
pip install apply_pr
sastre --help
```

For local development:

```console
git clone https://github.com/gisce/apply_pr.git
cd apply_pr
pip install -e .
```

## GitHub authentication

Set a token in the environment for unattended use:

```console
export GITHUB_TOKEN=github_token_value
```

If `GITHUB_TOKEN` is absent, `sastre` starts GitHub's device authorization
flow and displays a URL, a one-time code, and a QR code. The token needs access
to the repository and to GitHub deployments. Keep it out of shell history,
logs, and repository files.

`--owner` defaults to `gisce` and `--repository` defaults to `erp`. A repository
can also be written as `--repository owner/name`.

## SSH configuration

Remote deployments use the host, user, port, identity, and proxy settings from
your OpenSSH configuration. A target can be passed as a hostname or as an SSH
URL:

```console
sastre deploy --pr 123 --host deploy@example.net --environ pre
sastre deploy --pr 123 --host ssh://deploy@example.net:2222 --environ pre
```

To select a key explicitly, set `APPLY_PR_SSH_KEY_PATH` to its filesystem path.
Use `--proxy` for an SSH jump host. The default remote source root is
`/home/erp/src`, so the target checkout for the default repository is
`/home/erp/src/erp`.

## Deploying a pull request

### Commit-by-commit patches

The default mode downloads the pull request commits and applies them with
`git am`, preserving individual commits:

```console
sastre deploy \
  --pr 123 \
  --host deploy@example.net \
  --environ pre \
  --owner gisce \
  --repository erp
```

`--pr` also accepts a GitHub pull request URL. Use `--from-number N` or
`--from-commit SHA` to start at part of the pull request. `--squash` squashes
successfully applied commits into one commit after applying them.

### Single diff

Use `--as-diff` to apply the pull request as one diff instead of a patch series:

```console
sastre deploy \
  --pr https://github.com/gisce/erp/pull/123 \
  --host deploy@example.net \
  --environ pre \
  --as-diff
```

With `--as-diff`, `--from-commit` is excluded from the generated comparison;
it accepts either a commit SHA or a GitHub commit URL. `--reject` applies the
diff with reject handling. `--re-deploy` and `--as-diff` cannot be combined.
If a remote diff is missing, unreadable, empty, cannot be applied, or does not
produce a commit, the deployment is reported as failed. Use
`--exit-code-failure` when automation must also receive a non-zero exit code.

### Local checkout

Use `--local` to deploy directly to a local checkout, without SSH:

```console
sastre deploy --pr 123 --local --src /srv/src --environ test
```

`--local` cannot be combined with `--host` or `--proxy`.

### Relevant deploy options

Run `sastre deploy --help` for the authoritative full option list. Common
options include:

| Option | Behaviour |
| --- | --- |
| `--prs "123 124"` | Deploy multiple space-separated pull requests. |
| `--force-name NAME` | Use a different checkout directory name on the target. |
| `--force-hostname NAME` | Override the hostname recorded in GitHub. |
| `--re-deploy` | Resume from the last successful deployment commit. |
| `--skip-directory-pattern REGEX` | Exclude matching paths from patches or diffs. |
| `--skip-rolling-check` | Bypass the target rolling-branch check. |
| `--no-set-label` | Do not add the deployed environment label to the PR. |
| `--exit-code-failure` | Exit with status 1 when one of multiple PRs fails. |
| `--auto-exit BOOLEAN` | Control whether a failed `git am` is aborted automatically. |

Options that bypass checks or exclude paths change deployment safety and
should only be used after reviewing the generated change.
`--skip-directory-pattern` is a Python regular expression matched against full
repository-relative paths; the complete diff section for every matching file
is removed.

## Other commands

```console
# Update a GitHub deployment status
sastre status DEPLOYMENT_ID success --repository owner/name

# List deployment IDs and states for a pull request
sastre get_deploys 123 --repository owner/name

# Check the status of several pull requests
sastre check_prs --prs "123 124" --repository owner/name

# Mark a pull request as deployed without applying it
sastre mark_deployed --pr 123 --environ pre --repository owner/name

# Generate a milestone changelog under /tmp
sastre create_changelog --milestone 3.5.0 --repository owner/name
```

`sastre check_pr` and the `apply_pr` console command are deprecated. Use
`sastre deploy` for new automation.

## Development and tests

Install the project, then run the standard-library test suite:

```console
pip install -e .
python -m unittest discover -s tests
```

To validate the artifacts and the README rendering before a release:

```console
python setup.py sdist bdist_wheel
twine check dist/*
```

CI runs the test suite on Python 2.7 and Python 3.11. Contributions should
preserve both runtimes unless the support policy is deliberately changed.

## Project links

- [Source code](https://github.com/gisce/apply_pr)
- [Issue tracker](https://github.com/gisce/apply_pr/issues)
- [Releases and changelog](https://github.com/gisce/apply_pr/releases)
- [PyPI package](https://pypi.org/project/apply-pr/)
- [MIT license](https://github.com/gisce/apply_pr/blob/master/LICENSE)
