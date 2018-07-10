import logging
import os
from urlparse import urlparse

from fabric.tasks import execute, WrappedCallableTask
from fabric.api import env
import click

DEFAULT_LOG_LEVEL = 'ERROR'


def configure_logging():
    log_level = getattr(logging, os.environ.get(
        'LOG_LEVEL', DEFAULT_LOG_LEVEL).upper()
    )
    logging.basicConfig(level=log_level)


@click.command(name="apply_pr")
@click.option("--pr", help="Pull request to apply", required=True)
@click.option("--host", help="Host to apply", required=True)
@click.option("--from-number", help="From commit number", default=0)
@click.option("--from-commit", help="From commit hash (included)",
              default=None, show_default=True)
@click.option("--force-hostname", help="Force hostname",
              default=False, show_default=True)
@click.option('--owner', help='GitHub owner name',
              default='gisce', show_default=True)
@click.option('--repository', help='GitHub repository name',
              default='erp', show_default=True)
@click.option('--src', help='Remote src path',
              default='/home/erp/src', show_default=True)
def apply_pr(
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


@click.command(name='get_deploys')
@click.option('--pr', help='Pull request to check', required=True)
@click.option('--owner', help='GitHub owner name',
              default='gisce', show_default=True)
@click.option('--repository', help='GitHub repository name',
              default='erp', show_default=True)
def get_deploys(pr, owner, repository):
    from apply_pr import fabfile

    configure_logging()

    get_deploys_task = WrappedCallableTask(fabfile.get_deploys)
    execute(get_deploys_task, pr,
            owner=owner, repository=repository)


@click.command(name='status_pr')
@click.option('--deploy-id', help='Deploy id to mark')
@click.option('--status', type=click.Choice(['success', 'error', 'failure']),
              help='Status to set', default='success', show_default=True)
@click.option('--owner', help='GitHub owner name',
              default='gisce', show_default=True)
@click.option('--repository', help='GitHub repository name',
              default='erp', show_default=True)
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
@click.option('--owner', help='GitHub owner name',
              default='gisce', show_default=True)
@click.option('--repository', help='GitHub repository name',
              default='erp', show_default=True)
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


@click.command(name='check_prs_status')
@click.option('-m', '--milestone', required=True,
              help='Milestone to get the issues from (version)')
@click.option('--issues/--no-issues', default=False, show_default=True,
              help='Also get the data on the issues')
@click.option('--changelog_path', default='/tmp', show_default=True,
              help='Path to drop the changelog file in')
@click.option('--owner', help='GitHub owner name',
              default='gisce', show_default=True)
@click.option('--repository', help='GitHub repository name',
              default='erp', show_default=True)
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
    apply_pr()
