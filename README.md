## Apply pull requests

Tools to apply pull requests to remote servers or local checkouts using
`git format-patch` and `git am`.
Is integrated with the new [deployment
API](https://developer.github.com/v3/repos/deployments/) from GitHub.

To use you must [generate an OAuth token](https://github.com/settings/tokens/new)
from GitHub and set to the `GITHUB_TOKEN` environment variable.

SSH connections use the standard `~/.ssh/config` file. If the private key must
be provided explicitly, set `APPLY_PR_SSH_KEY_PATH` with the key file path
before running the command. When the target host requires a jump server, pass
`--proxy user@proxy-host`, equivalent to using `ssh -J user@proxy-host`.

Local deployments use `--local` and execute Git directly in the target checkout;
they do not open an SSH connection and do not use `sudo`. `--src` keeps the same
meaning in both modes: it is the parent directory containing the repository.
For example, `--src /home/user/src --repository erp` targets
`/home/user/src/erp`. The local checkout must be clean before deployment so
existing work cannot accidentally be included in the applied PR.

## Command line scripts

This repository uses the [Click](http://click.pocoo.org/5/) package to
register commands that call the fabric scripts.

The following commands are supported with `sastre`:

| Console Command    | Description                                                         | Wiki page                                                                                          |
|:---------------:   |:--------------------------------------------------------------------|:---------------------------------------------------------------------------------------------------|
| `deploy`           | Apply a PR to a remote server or local checkout                     | [Deploy a pull request](https://github.com/gisce/apply_pr/wiki/Apply-a-Pull-Request)               |
| `check_prs`        | Check the status of the PRs for a set of PRs                        | [Check pull requests status](https://github.com/gisce/apply_pr/wiki/Check-pull-requests-status)    |
| `status`           | Update the status of a deploy into GitHub                           | [Mark deploy status](https://github.com/gisce/apply_pr/wiki/Mark-deploy-status)                    |
| `create_changelog` | Create a chnagelog for the given milestone                          | [Create Changelog](https://github.com/gisce/apply_pr/wiki/Create-Changelog)                        |
| `check_pr`         | **Deprecated:** Check if the PR's commits are applied on the server | [Check Applied patches](https://github.com/gisce/apply_pr/wiki/Check-applied-patches-(deprecated)) |

## Install

```bash
# Install from Pypi
pip install apply_pr
```

## Usage

**NOTE**: do not include braces on the following commands

### DEPLOY

```bash
Usage: deploy [OPTIONS]

Options:
  --pr TEXT              Pull request to deploy  [required]
  --host TEXT            Remote host (required unless --local is used)
  --local                Apply directly to a local checkout without SSH
  --proxy TEXT           SSH proxy/jump host
  --src TEXT             Parent path containing the repository
  --from-number INTEGER  From commit number
  --from-commit TEXT     From commit hash (included)
  --squash               Squash successfully applied commits into one
  --force-hostname TEXT  Force hostname  [default: False]
  --owner TEXT           GitHub owner name  [default: gisce]
  --repository TEXT      GitHub repository name  [default: erp]
  --src TEXT             Remote src path  [default: /home/erp/src]
  --help                 Show this message and exit.
```

Local example:

```bash
sastre deploy --local --src /home/user/src --repository erp \
  --pr 1234 --environ test
```

### STATUS

```bash
Usage: status [OPTIONS]

Options:
  --deploy-id TEXT                Deploy id to mark
  --status [success|error|failure]
                                  Status to set  [default: success]
  --owner TEXT                    GitHub owner name  [default: gisce]
  --repository TEXT               GitHub repository name  [default: erp]
  --help                          Show this message and exit.
```

### CHECK PRS

```bash
Usage: check_prs [OPTIONS]

Options:
  --prs TEXT         List of pull request separated by space (by default)
                     [required]
  --separator TEXT   Character separator of list by default is space
                     [default:  ; required]
  --owner TEXT       GitHub owner name  [default: gisce]
  --repository TEXT  GitHub repository name  [default: erp]
  --help             Show this message and exit.
```

### CREATE CHANGELOG

```bash
Usage: create_changelog [OPTIONS]

Options:
  -m, --milestone TEXT    Milestone to get the issues from (version)
                          [required]
  --issues / --no-issues  Also get the data on the issues  [default: False]
  --changelog_path TEXT   Path to drop the changelog file in  [default: /tmp]
  --owner TEXT            GitHub owner name  [default: gisce]
  --repository TEXT       GitHub repository name  [default: erp]
  --help                  Show this message and exit.
```

### CHECK PR (deprecated)

```bash
Usage: check_pr [OPTIONS]

Options:
  --pr TEXT          Pull request to check  [required]
  --host TEXT        Host to check  [required]
  --proxy TEXT       SSH proxy/jump host
  --owner TEXT       GitHub owner name  [default: gisce]
  --repository TEXT  GitHub repository name  [default: erp]
  --src TEXT         Remote src path  [default: /home/erp/src]
  --help             Show this message and exit.
```
