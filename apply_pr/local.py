# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function, unicode_literals

import glob
import logging
import os
import shutil
import socket
import subprocess
import tempfile
from contextlib import contextmanager

import six
from fabric import colors
from tqdm import tqdm

from apply_pr.exceptions import ApplyError
from apply_pr.console import (
    as_text as _as_text, console_message, log_error,
    print_message as _print_message,
)


logger = logging.getLogger(__name__)


try:
    console_input = raw_input
except NameError:
    console_input = input


class LocalApplyError(ApplyError):
    pass


class CommandResult(object):
    def __init__(self, return_code, output):
        self.return_code = return_code
        self.output = output

    @property
    def failed(self):
        return self.return_code != 0


def _log_error(error, prefix=None):
    log_error(logger, error, prefix=prefix)


def _tqdm_write(message):
    tqdm.write(console_message(message))


def repository_path(src, repository):
    """Return the checkout path using the same src/repository layout as SSH."""
    return os.path.abspath(os.path.join(os.path.expanduser(src), repository))


def _run_git(checkout, arguments, check=True):
    command = ['git'] + list(arguments)
    process = subprocess.Popen(
        command,
        cwd=checkout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = process.communicate()[0]
    if not isinstance(output, six.text_type):
        output = output.decode('utf-8', 'replace')
    result = CommandResult(process.returncode, output)
    if check and result.failed:
        raise LocalApplyError(
            "Command '{command}' failed in {checkout}:\n{output}".format(
                command=' '.join(command),
                checkout=checkout,
                output=output.strip(),
            )
        )
    return result


def _git_path(checkout, name):
    path = _run_git(
        checkout, ['rev-parse', '--git-path', name]
    ).output.strip()
    if not os.path.isabs(path):
        path = os.path.join(checkout, path)
    return os.path.abspath(path)


def validate_repository(checkout, skip_rolling_check=False):
    """Validate the local target before any deployment is registered."""
    if not os.path.isdir(checkout):
        raise LocalApplyError(
            'The local repository does not exist: {}'.format(checkout)
        )

    top_level = _run_git(
        checkout, ['rev-parse', '--show-toplevel'], check=False
    )
    if top_level.failed:
        raise LocalApplyError(
            'The local target is not a Git repository: {}'.format(checkout)
        )
    if os.path.realpath(top_level.output.strip()) != os.path.realpath(checkout):
        raise LocalApplyError(
            'The local target must be the repository root: {}'.format(checkout)
        )

    if os.path.isdir(_git_path(checkout, 'rebase-apply')):
        raise LocalApplyError(
            'The local repository is in the middle of a git am session'
        )

    if not skip_rolling_check:
        branch = _run_git(
            checkout, ['symbolic-ref', '--quiet', '--short', 'HEAD'],
            check=False,
        )
        if branch.failed or branch.output.strip() != 'rolling':
            raise LocalApplyError(
                "The local repository is not on the 'rolling' branch"
            )

    status = _run_git(checkout, ['status', '--porcelain'])
    if status.output.strip():
        raise LocalApplyError(
            'The local repository has uncommitted changes; clean or stash '
            'them before deploying'
        )


@contextmanager
def _working_directory(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _patch_number(path):
    try:
        return int(os.path.basename(path).split('-', 1)[0])
    except (TypeError, ValueError):
        return 0


def _select_patches(workdir, pr_number, from_number=0):
    patch_pattern = os.path.join(
        workdir, 'deploy', 'patches', str(pr_number), '*.patch'
    )
    patches = sorted(glob.glob(patch_pattern))
    from_number = int(from_number or 0)
    if from_number:
        patches = [
            path for path in patches if _patch_number(path) >= from_number
        ]
    if not patches:
        raise LocalApplyError(
            'No patches found to apply for pull request #{}'.format(pr_number)
        )
    return patches


def _apply_patches(
    checkout, patches, auto_exit=True, input_func=None, squash=False,
    pr_number=None
):
    input_func = input_func or console_input
    progress = tqdm(total=len(patches), desc='   Applying')
    previous_head = None
    if squash:
        previous_head = _run_git(
            checkout, ['rev-parse', 'HEAD']
        ).output.strip()
    try:
        result = _run_git(checkout, ['am'] + patches, check=False)
        while True:
            for line in result.output.split('\n'):
                if line.startswith('Applying: '):
                    _tqdm_write(colors.green(line))
                    progress.update()
            if not result.failed:
                if squash:
                    _run_git(checkout, ['reset', '--soft', previous_head])
                    _run_git(
                        checkout,
                        [
                            'commit', '-m',
                            'Apply pull request #{}'.format(pr_number),
                        ],
                    )
                return
            if 'git config --global user.email' in result.output:
                _log_error('Need to configure git for this user')
                raise LocalApplyError(result.output.strip())
            if auto_exit:
                _run_git(checkout, ['am', '--abort'], check=False)
                logger.error('Aborting deploy and go back')
                raise LocalApplyError(result.output.strip())

            input_func(
                'Resolve the git am conflict, stage the resolution and press '
                'Enter to continue: '
            )
            staged = _run_git(
                checkout,
                ['diff', '--cached', '--name-only', '--no-color'],
            ).output.strip()
            action = '--continue' if staged else '--skip'
            result = _run_git(checkout, ['am', action], check=False)
    finally:
        progress.close()


def _apply_diff(
    checkout, diff_path, pr_number, reject=False, input_func=None
):
    input_func = input_func or console_input
    arguments = ['apply']
    if reject:
        arguments.append('--reject')
    arguments.append(diff_path)
    _print_message(colors.green('Applying diff {}'.format(diff_path)))
    result = _run_git(checkout, arguments, check=False)
    if result.failed and not reject:
        raise LocalApplyError(result.output.strip())
    if result.failed:
        _print_message(colors.yellow('Some rejects ...'))
        input_func(
            'Some hunks were rejected. Resolve them and press Enter to '
            'continue: '
        )

    changed = _run_git(checkout, ['status', '--porcelain']).output.strip()
    if not changed:
        _print_message(colors.green('Nothing to commit! Continue'))
        return
    _print_message(colors.green('Commit!'))
    _run_git(checkout, ['add', '-A'])
    _run_git(
        checkout,
        ['commit', '-m', 'Apply pull request #{}'.format(pr_number)],
    )


def _mark_failure(
    backend, deploy_id, error, owner, repository, no_set_label
):
    try:
        backend.mark_deploy_status(
            deploy_id,
            state='error',
            description='{}'.format(error),
            owner=owner,
            repository=repository,
            no_set_label=no_set_label,
        )
    except Exception as status_error:
        _log_error(
            status_error,
            prefix='Could not mark the local deployment as failed: ',
        )


def apply_pr(
    backend, pr_number, from_number=0, from_commit=None, hostname=False,
    src='/home/erp/src', owner='gisce', repository='erp', auto_exit=False,
    force_name=None, re_deploy=False, as_diff=False, environment='pro',
    reject=False, skip_rolling_check=False, no_set_label=False,
    input_func=None, squash=False, skip_directory_pattern=None
):
    """Apply a GitHub pull request directly to a local checkout."""
    repository_name = force_name or repository
    checkout = repository_path(src, repository_name)
    hostname = hostname or socket.gethostname()
    input_func = input_func or console_input

    try:
        validate_repository(
            checkout, skip_rolling_check=skip_rolling_check
        )

        if re_deploy:
            _tqdm_write(colors.blue(
                '\U0001F50E Trying to find last success deploymnet...'
            ))
            last_deploy, from_commit = backend.get_last_deploy(
                pr_number, hostname, owner, repository
            )
            if last_deploy:
                _tqdm_write(colors.blue(
                    '\U00002705 Got it! is {sha}.'.format(**last_deploy)
                ))
                if last_deploy['sha'] == from_commit:
                    _tqdm_write(colors.red(
                        '\U000026D4 No commits to deploy...'
                    ))
                    raise LocalApplyError('No commits to deploy')
            else:
                _tqdm_write(colors.blue('\U0001F62F Not found...'))
            response = input_func(
                'Deploy locally from {}? (y/n): '.format(from_commit or '0')
            )
            if response.upper() != 'Y':
                raise LocalApplyError('Local deployment cancelled')

        deploy_id = backend.mark_to_deploy(
            pr_number,
            hostname=hostname,
            owner=owner,
            repository=repository,
        )
    except Exception as error:
        _log_error(error)
        _tqdm_write(colors.red('Deploy failure \U0001F680'))
        return False

    if not deploy_id:
        _tqdm_write(colors.magenta(
            'No deploy id! you must mark the Pull Request manually'
        ))

    workdir = tempfile.mkdtemp(prefix='sastre-local-')
    try:
        backend.mark_deploy_status(
            deploy_id,
            state='pending',
            owner=owner,
            repository=repository,
            environment=environment,
            no_set_label=no_set_label,
        )
        _tqdm_write(colors.yellow(
            'Marking to deploy ({}) \U0001F680'.format(deploy_id)
        ))
        with _working_directory(workdir):
            if as_diff:
                backend.export_diff_from_github(
                    pr_number, owner=owner, repository=repository,
                    from_commit=from_commit,
                    skip_directory_pattern=skip_directory_pattern,
                )
            else:
                backend.export_patches_from_github(
                    pr_number,
                    from_commit,
                    owner=owner,
                    repository=repository,
                    skip_directory_pattern=skip_directory_pattern,
                )

        if as_diff:
            _tqdm_write(colors.yellow('Applying diff \U0001F648'))
            diff_path = os.path.join(
                workdir, 'deploy', 'patches', '{}.diff'.format(pr_number)
            )
            if not os.path.isfile(diff_path):
                raise LocalApplyError(
                    'The pull request diff was not downloaded'
                )
            if os.path.getsize(diff_path):
                _apply_diff(
                    checkout,
                    diff_path,
                    pr_number,
                    reject=reject,
                    input_func=input_func,
                )
            else:
                _tqdm_write(colors.green('Nothing to commit! Continue'))
        else:
            _tqdm_write(colors.yellow('Applying patches \U0001F648'))
            try:
                patches = _select_patches(
                    workdir,
                    pr_number,
                    from_number=0 if from_commit else from_number,
                )
            except LocalApplyError:
                if not skip_directory_pattern:
                    raise
                patches = []
            if patches:
                _apply_patches(
                    checkout,
                    patches,
                    auto_exit=auto_exit,
                    input_func=input_func,
                    squash=squash,
                    pr_number=pr_number,
                )
            else:
                _tqdm_write(colors.green('Nothing to commit! Continue'))

        backend.mark_deploy_status(
            deploy_id,
            state='success',
            owner=owner,
            repository=repository,
            pr_number=pr_number,
            no_set_label=no_set_label,
            environment=environment,
        )
        _tqdm_write(colors.green('Deploy success \U0001F680'))
        return True
    except Exception as error:
        _log_error(error)
        _mark_failure(
            backend,
            deploy_id,
            error,
            owner,
            repository,
            no_set_label,
        )
        _tqdm_write(colors.red('Deploy failure \U0001F680'))
        return False
    finally:
        shutil.rmtree(workdir)
