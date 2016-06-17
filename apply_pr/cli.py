import logging
import os

from fabric.tasks import execute, WrappedCallableTask
import click


@click.command(name="apply_pr")
@click.option("--pr", help="Pull request to apply", required=True)
@click.option("--from-number", help="With commit number", default=0)
def apply_pr(pr, from_number):
    from apply_pr import fabfile

    log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
    logging.basicConfig(level=log_level)

    apply_pr_task = WrappedCallableTask(fabfile.apply_pr)
    execute(apply_pr_task, pr, from_number)


if __name__ == '__main__':
    apply_pr()
