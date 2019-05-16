import logging
import os
from urlparse import urlparse

from fabric.tasks import execute, WrappedCallableTask
from fabric.api import env
from fabric import colors
import click

DEFAULT_LOG_LEVEL = 'ERROR'

github_options = [
    click.option('--owner', help='GitHub owner name', default='gisce', show_default=True),
    click.option('--repository', help='GitHub repository name', default='erp', show_default=True),

]

deployment_options = [
    click.option("--host", help="Host to apply", required=True),
    click.option('--src', help='Remote src path',  default='/home/erp/src', show_default=True),
    click.option('--sudo_user', help='Sudo user from the host', default='erp', show_default=True),
]

apply_pr_options = github_options + deployment_options + [
    click.option("--pr", help="Pull request to apply", required=True),
    click.option("--from-number", help="From commit number", default=0),
    click.option("--from-commit", help="From commit hash (included)", default=None),
    click.option("--force-hostname", help="Force hostname",  default=False),
]

status_options = github_options + [
    click.argument('deploy-id'),
    click.argument(
        'status', type=click.Choice(['success', 'error', 'failure']),
        default='success'),
]

check_prs_options = github_options + [
    click.option('--prs', required=True,
        help='List of pull request separated by space (by default)'),
    click.option(
        '--separator', help='Character separator of list by default is space',
        default=' ', show_default=True),
    click.option('--version',
        help="Compare with milestone and show if included in prs"),
]

create_changelog_options = github_options + [
    click.option('-m', '--milestone', required=True,
        help='Milestone to get the issues from (version)'),
    click.option('--issues/--no-issues', default=False, show_default=True,
        help='Also get the data on the issues'),
    click.option('--changelog_path', default='/tmp', show_default=True,
        help='Path to drop the changelog file in'),
]

def add_options(options):
    def _add_options(func):
        for option in reversed(options):
            func = option(func)
        return func
    return _add_options


def configure_logging():
    log_level = getattr(logging, os.environ.get(
        'LOG_LEVEL', DEFAULT_LOG_LEVEL).upper()
    )
    logging.basicConfig(level=log_level)


@click.command('apply_pr')
@add_options(apply_pr_options)
def deprecated(**kwargs):
    print(colors.red(
        "WARNING: 'apply_pr' command has been deprecated and\n"
        "  it will be deleted in future versions"
    ))
    print(colors.yellow("> Use 'sastre deploy' instead"))
    return apply_pr(**kwargs)


@click.group(name='sastre')
def sastre(**kwargs):
    from apply_pr.version import check_version
    check_version()


def apply_pr(
    pr, host, from_number=0, from_commit=None, force_hostname=False,
    owner='gisce', repository='erp', src='/home/erp/src', sudo_user='erp',
    auto_exit=False
):
    """
    Deploy a PR into a remote server via Fabric
    :param pr:              Number of the PR to deploy
    :type pr:               str
    :param host:            Host to connect
    :type host:             str
    :param from_number:     Number of the commit to deploy from
    :type from_number:      str
    :param from_commit:     Hash of the commit to deploy from
    :type from_commit:      str
    :param force_hostname:  Hostname used in GitHub
    :type force_hostname:   str
    :param owner:           Owner of the repository of GitHub
    :type owner:            str
    :param repository:      Name of the repository of GitHub
    :type repository:       str
    :param src:             Source path to the repository directory
    :type src:              str
    :param sudo_user:       Remote user with sudo
    :type sudo_user         str
    """
    from apply_pr import fabfile
    if 'ssh' not in host and host[:2] != '//':
        host = '//{}'.format(host)
    url = urlparse(host, scheme='ssh')
    env.user = url.username
    env.password = url.password

    configure_logging()
    apply_pr_task = WrappedCallableTask(fabfile.apply_pr)
    result = execute(
        apply_pr_task, pr, from_number, from_commit, hostname=force_hostname,
        src=src, owner=owner, repository=repository, sudo_user=sudo_user,
        host='{}:{}'.format(url.hostname, (url.port or 22)), auto_exit=auto_exit
    )
    return result


@sastre.command(name="deploy")
@add_options(apply_pr_options)
def deploy(**kwargs):
    """Deploy a PR into a remote server via Fabric"""
    return apply_pr(**kwargs)


@sastre.command(name='check_pr')
@click.option('--pr', help='Pull request to check', required=True)
@click.option('--force/--no-force', default=False,
              help='Forces the usage of this command')
@add_options(deployment_options)
def check_pr(pr, force, src, owner, repository, host):
    """DEPRECATED - Check for applied commits on PR"""
    print(colors.red("This option has been deprecated as it doesn't work"))
    if not force:
        print(colors.red(
            "Use '--force' to force the usage for this command (as is)"))
        exit()
    from apply_pr import fabfile

    url = urlparse(host, scheme='ssh')
    env.user = url.username
    env.password = url.password

    configure_logging()

    check_pr_task = WrappedCallableTask(fabfile.check_pr)
    execute(
        check_pr_task, pr, src=src, owner=owner, repository=repository,
        host='{}:{}'.format(url.hostname, (url.port or 22))
    )


def status_pr(deploy_id, status, owner, repository):
    """Update the status of a deploy into GitHub"""
    from apply_pr import fabfile

    configure_logging()

    mark_deploy_status = WrappedCallableTask(fabfile.mark_deploy_status)
    execute(mark_deploy_status, deploy_id, status,
            owner=owner, repository=repository)


@sastre.command(name='status')
@add_options(status_options)
def status(**kwargs):
    """Update the status of a deploy into GitHub"""
    status_pr(**kwargs)


def check_prs_status(prs, separator, version, owner, repository):
    """Check the status of the PRs for a set of PRs"""
    from apply_pr import fabfile

    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
    logging.basicConfig(level=log_level)

    check_pr_task = WrappedCallableTask(fabfile.prs_status)
    execute(check_pr_task, prs,
            owner=owner,
            repository=repository,
            separator=separator,
            version=version)


@sastre.command(name='check_prs')
@add_options(check_prs_options)
def check_prs(**kwargs):
    """Check the status of the PRs for a set of PRs"""
    check_prs_status(**kwargs)


@sastre.command(name='create_changelog')
@add_options(create_changelog_options)
def create_changelog(milestone, issues, changelog_path, owner, repository):
    """Create a changelog for the given milestone"""
    from apply_pr import fabfile

    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
    logging.basicConfig(level=log_level)
    changelog_task = WrappedCallableTask(fabfile.create_changelog)
    execute(changelog_task,
            milestone,
            issues,
            changelog_path,
            owner=owner,
            repository=repository)


def deploy_ids(pr, owner, repository):
    from apply_pr import fabfile

    configure_logging()

    get_deploys_task = WrappedCallableTask(fabfile.get_deploys)
    execute(get_deploys_task, pr,
            owner=owner, repository=repository)


@sastre.command(name='get_deploys')
@click.argument('PR')
@add_options(github_options)
def get_deploys(**kwargs):
    """Get deploy IDs and their status for a given PR number"""
    deploy_ids(**kwargs)


if __name__ == '__main__':
    sastre()
