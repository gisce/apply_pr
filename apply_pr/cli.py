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
@click.option("--from-commit", help="From commit hash", default=None)
def apply_pr(pr, host, from_number, from_commit):
    from apply_pr import fabfile

    url = urlparse(host)
    env.user = url.username
    env.password = url.password

    configure_logging()

    apply_pr_task = WrappedCallableTask(fabfile.apply_pr)
    execute(apply_pr_task, pr, from_number, from_commit, host=url.hostname)


@click.command(name='check_pr')
@click.option('--pr', help='Pull request to check', required=True)
@click.option('--host', help='Host to check', required=True)
def check_pr(pr, host):
    from apply_pr import fabfile

    url = urlparse(host)
    env.user = url.username
    env.password = url.password

    configure_logging()

    check_pr_task = WrappedCallableTask(fabfile.check_pr)
    execute(check_pr_task, pr, host=url.hostname)


@click.command(name='status_pr')
@click.option('--deploy-id', help='Deploy id to mark')
@click.option('--status', help='Status to set.', default='success',
              type=click.Choice(['success', 'error', 'failure']))
def status_pr(deploy_id, status):
    from apply_pr import fabfile

    configure_logging()

    mark_deploy_status = WrappedCallableTask(fabfile.mark_deploy_status)
    execute(mark_deploy_status, deploy_id, status)


@click.command(name='check_prs_status')
@click.option('--prs', help='List of pull request separated by space(by default)', required=True)
@click.option('--separator', help='Character separator of list by default is space', default=' ', required=True)
def check_prs_status(prs, separator):
    from apply_pr import fabfile

    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
    logging.basicConfig(level=log_level)

    check_pr_task = WrappedCallableTask(fabfile.prs_status)
    execute(check_pr_task, prs, separator=separator)

if __name__ == '__main__':
    apply_pr()
