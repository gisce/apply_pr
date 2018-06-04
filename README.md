## Apply pull requests

Fabric tools to apply pull requests in servers using `git format-patch` and
`git am`.
Is integrated with the new [deployment
API](https://developer.github.com/v3/repos/deployments/) from GitHub.

To use you must [generate an OAuth token](https://github.com/settings/tokens/new)
from GitHub and set to the `GITHUB_TOKEN` environment variable.

## Command line scripts

This repository uses the [Click](http://click.pocoo.org/5/) package to
register commands that call the fabric scripts.

The following commands are supported with apply_pr:

| Console Command | Description                                                                 | Wiki page                                                                             |
|:---------------:|:----------------------------------------------------------------------------|:--------------------------------------------------------------------------------------|
|     apply_pr    | Apply a PR to a remote server                                               | [Apply a Pull Request](https://github.com/gisce/apply_pr/wiki/Apply-a-Pull-Request)   |
|     check_pr    | Check if the PR's commits are applied on the server                         | [Check Applied patches](https://github.com/gisce/apply_pr/wiki/Check-Applied-patches) |
|    status_pr    | Update the deploy status on GitHub for the PR                               | [Mark deploy status](https://github.com/gisce/apply_pr/wiki/Mark-deploy-status)       |
| check_prs_status| Check the PRs status (whether they are or not merged and at which milestone)| [Check PRs Status](https://github.com/gisce/apply_pr/wiki/Check-the-PRs-status)       |
| create_changelog| Creates the changelog for all PRs merged in a milestone                     | [Create Changelog](https://github.com/gisce/apply_pr/wiki/Create-Changelog)           |


## Install

```bash
# Install from Pypi
pip install apply_pr
```

## Usage

**NOTE**: do not include braces on the following commands

### APPLY PR

```bash
Usage: apply_pr [OPTIONS]

Options:
  --pr TEXT              Pull request to apply  [required]
  --host TEXT            Host to apply  [required]
  --from-number INTEGER  From commit number
  --from-commit TEXT     From commit hash (included)
  --force-hostname TEXT  Force hostname  [default: False]
  --owner TEXT           GitHub owner name  [default: gisce]
  --repository TEXT      GitHub repository name  [default: erp]
  --src TEXT             Remote src path  [default: /home/erp/src]
  --help                 Show this message and exit.
```

### CHECK PR

```bash
Usage: check_pr [OPTIONS]

Options:
  --pr TEXT          Pull request to check  [required]
  --host TEXT        Host to check  [required]
  --owner TEXT       GitHub owner name  [default: gisce]
  --repository TEXT  GitHub repository name  [default: erp]
  --src TEXT         Remote src path  [default: /home/erp/src]
  --help             Show this message and exit.
```

### STATUS PR

```bash
Usage: status_pr [OPTIONS]

Options:
  --deploy-id TEXT                Deploy id to mark
  --status [success|error|failure]
                                  Status to set  [default: success]
  --owner TEXT                    GitHub owner name  [default: gisce]
  --repository TEXT               GitHub repository name  [default: erp]
  --help                          Show this message and exit.
```

### CHECK PRS STATUS

```bash
Usage: check_prs_status [OPTIONS]

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