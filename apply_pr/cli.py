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

deployment_options = github_options + [
    click.option("--host", help="Host to apply", required=True),
    click.option('--src', help='Remote src path',  default='/home/erp/src', show_default=True),
]

apply_pr_options = deployment_options + [
    click.option("--pr", help="Pull request to apply", required=True),
    click.option("--from-number", help="From commit number", default=0),
    click.option("--from-commit", help="From commit hash (included)", default=None),
    click.option("--force-hostname", help="Force hostname",  default=False)
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


@click.command(name="sastre")
@add_options(apply_pr_options)
def sastre(
        pr, host, from_number, from_commit, force_hostname,
        owner, repository, src
):
    from apply_pr.version import check_version
    check_version()

    from apply_pr import fabfile

    url = urlparse(host)
    env.user = url.username
    env.password = url.password

    configure_logging()

    apply_pr_task = WrappedCallableTask(fabfile.apply_pr)
    execute(
        apply_pr_task, pr, from_number, from_commit, force_hostname,
        src=src, owner=owner, repository=repository,
        host=url.hostname
    )

@click.command()
@add_options(apply_pr_options)
def tailor(**kwargs):
    sastre()

@click.command()
@add_options(apply_pr_options)
def apply_pr(**kwargs):
    """You can apply patches using 'sastre' or 'tailor'.\n
    Use 'sastre --help' or 'tailor --help' for more information."""
    print(colors.yellow(
        "You can apply patches using 'sastre' or 'tailor'.\n"
        "Use 'sastre --help' or 'tailor --help' for more information."
    ))
    sastre()


@click.command(name='check_pr')
@click.option('--pr', help='Pull request to check', required=True)
@add_options(deployment_options)
def check_pr(pr, src, owner, repository, host):
    from apply_pr import fabfile

    url = urlparse(host)
    env.user = url.username
    env.password = url.password

    configure_logging()

    check_pr_task = WrappedCallableTask(fabfile.check_pr)
    execute(check_pr_task, pr,
            src=src, owner=owner, repository=repository, host=url.hostname)


@click.command(name='status_pr')
@click.option('--deploy-id', help='Deploy id to mark')
@click.option('--status', type=click.Choice(['success', 'error', 'failure']),
              help='Status to set', default='success', show_default=True)
@add_options(github_options)
def status_pr(deploy_id, status, owner, repository):
    from apply_pr import fabfile

    configure_logging()

    mark_deploy_status = WrappedCallableTask(fabfile.mark_deploy_status)
    execute(mark_deploy_status, deploy_id, status,
            owner=owner, repository=repository)


@click.command(name='check_prs_status')
@click.option('--prs', required=True,
              help='List of pull request separated by space (by default)')
@click.option('--separator',
              help='Character separator of list by default is space',
              default=' ', required=True, show_default=True)
@click.option('--version',
              help="Compare with milestone and show if included in prs")
@add_options(github_options)
def check_prs_status(prs, separator, version, owner, repository):
    from apply_pr import fabfile

    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
    logging.basicConfig(level=log_level)

    check_pr_task = WrappedCallableTask(fabfile.prs_status)
    execute(check_pr_task, prs,
            owner=owner,
            repository=repository,
            separator=separator,
            version=version)


@click.command(name='create_changelog')
@click.option('-m', '--milestone', required=True,
              help='Milestone to get the issues from (version)')
@click.option('--issues/--no-issues', default=False, show_default=True,
              help='Also get the data on the issues')
@click.option('--changelog_path', default='/tmp', show_default=True,
              help='Path to drop the changelog file in')
@add_options(github_options)
def create_changelog(milestone, issues, changelog_path, owner, repository):
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


if __name__ == '__main__':
    sastre()
