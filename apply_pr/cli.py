import logging
import os
from urlparse import urlparse

from fabric.tasks import execute, WrappedCallableTask
from fabric.api import env
import click


@click.command(name="apply_pr")
@click.option("--pr", help="Pull request to apply", required=True)
@click.option("--host", help="Host to apply", required=True)
@click.option("--from-number", help="With commit number", default=0)
def apply_pr(pr, host, from_number):
    from apply_pr import fabfile

    url = urlparse(host)
    env.user = url.username
    env.password = url.password

    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
    logging.basicConfig(level=log_level)

    apply_pr_task = WrappedCallableTask(fabfile.apply_pr)
    execute(apply_pr_task, pr, from_number, host=url.hostname)


@click.command(name='check_pr')
@click.option('--pr', help='Pull request to check', required=True)
@click.option('--host', help='Host to check', required=True)
def check_pr(pr, host):
    from apply_pr import fabfile

    url = urlparse(host)
    env.user = url.username
    env.password = url.password

    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
    logging.basicConfig(level=log_level)

    check_pr_task = WrappedCallableTask(fabfile.check_pr)
    execute(check_pr_task, pr, host=url.hostname)

if __name__ == '__main__':
    apply_pr()
