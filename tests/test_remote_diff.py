# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import io
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import six
import requests
from fabric.api import env
from fabric.utils import abort

from apply_pr import fabfile


class LoggingCapture(object):
    def __init__(self):
        self.value = u''

    def write(self, value):
        if not isinstance(value, six.text_type):
            value = value.decode('utf-8')
        self.value += value

    def flush(self):
        pass

    def getvalue(self):
        return self.value


class RemoteResult(six.text_type):
    def __new__(cls, value, return_code=0):
        result = super(RemoteResult, cls).__new__(cls, value)
        result.return_code = return_code
        result.failed = return_code != 0
        result.succeeded = not result.failed
        return result


class RemoteBytesResult(bytes):
    """Mimic the raw byte output fabric returns for remote commands on PY2."""

    def __new__(cls, value, return_code=0):
        result = super(RemoteBytesResult, cls).__new__(cls, value)
        result.return_code = return_code
        result.failed = return_code != 0
        result.succeeded = not result.failed
        return result


class RemoteDiffDeploymentTest(unittest.TestCase):
    """Exercise the remote workflow using real Git and a local sudo transport."""

    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix='sastre-remote-diff-test-')
        self.checkout = os.path.join(self.tempdir, 'erp')
        os.makedirs(self.checkout)
        self._git('init', '-q')
        self._git('config', 'user.name', 'Sastre Test')
        self._git('config', 'user.email', 'sastre@example.net')
        self._git('checkout', '-q', '-b', 'rolling')
        self._write('.gitignore', 'patches/\n')
        self._write('message.txt', 'before\n')
        self._git('add', '-A')
        self._git('commit', '-q', '-m', 'Initial commit')
        self._write('message.txt', 'after\n')
        diff = self._git('diff')
        self._git('checkout', '--', 'message.txt')
        os.makedirs(os.path.join(self.checkout, 'patches', '42'))
        self.diff_path = 'patches/42/42.diff'
        self._write(self.diff_path, diff)
        self.previous_head = self._git('rev-parse', 'HEAD').strip()
        self.statuses = []
        self.commands = []
        self.messages = []
        self.overrides = {}
        self.probe_notice = ''

        self.old_backend = {}
        for name, replacement in (
            ('sudo', self._sudo),
            ('mark_to_deploy', lambda *args, **kwargs: 123),
            ('mark_deploy_status', self._mark_status),
            ('export_diff_from_github', lambda *args, **kwargs: (None, None)),
            ('upload_diff', lambda *args, **kwargs: None),
            ('prompt', lambda *args, **kwargs: ''),
        ):
            self.old_backend[name] = getattr(fabfile, name)
            setattr(fabfile, name, replacement)
        self.old_write = fabfile.tqdm.write
        fabfile.tqdm.write = self._capture_message
        self.old_environment = dict(
            (key, env[key]) for key in ('sudo_prefix', 'sudo_user', 'warn_only')
        )
        self.error_stream = LoggingCapture()
        self.error_handler = logging.StreamHandler(self.error_stream)
        fabfile.logger.addHandler(self.error_handler)

    def tearDown(self):
        fabfile.logger.removeHandler(self.error_handler)
        for name, value in self.old_backend.items():
            setattr(fabfile, name, value)
        fabfile.tqdm.write = self.old_write
        env.update(self.old_environment)
        shutil.rmtree(self.tempdir)

    def _write(self, relative_path, content):
        with io.open(os.path.join(self.checkout, relative_path), 'w', encoding='utf-8') as stream:
            stream.write(content)

    def _git(self, *arguments):
        return subprocess.check_output(
            ['git'] + list(arguments), cwd=self.checkout,
            stderr=subprocess.STDOUT,
        ).decode('utf-8', 'replace')

    def _sudo(self, command, user=None, **kwargs):
        self.commands.append((command, user or env.sudo_user))
        if command in self.overrides:
            result = self.overrides[command]
        else:
            process = subprocess.Popen(
                ['/bin/sh', '-c', command], cwd=self.checkout,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            output = process.communicate()[0].decode('utf-8', 'replace')
            if command.startswith('test '):
                output = self.probe_notice + output
            result = RemoteResult(output, process.returncode)
        if result.failed and not env.warn_only:
            abort('Remote command failed: {}\n{}'.format(command, result))
        return result

    def _mark_status(self, deploy_id, state='success', **kwargs):
        self.statuses.append((state, kwargs))

    def _capture_message(self, message):
        if not isinstance(message, six.text_type):
            message = message.decode('utf-8')
        self.messages.append(message)

    def _deploy(self, **kwargs):
        return fabfile.apply_pr(
            '42', src=self.tempdir, repository='erp', as_diff=True, **kwargs
        )

    def _assert_failure(self, diagnostic):
        self.assertEqual([state for state, details in self.statuses], ['pending', 'error'])
        self.assertIn(diagnostic, self.statuses[-1][1]['description'])
        self.assertIn(diagnostic, self.error_stream.getvalue())
        self.assertTrue(any('Deploy failure' in message for message in self.messages))
        self.assertFalse(any('Deploy success' in message for message in self.messages))
        self.assertEqual(env.sudo_prefix, self.old_environment['sudo_prefix'])

    def test_shell_notice_does_not_skip_diff_or_commit(self):
        self.probe_notice = 'Remote shell notice\n'

        self.assertTrue(self._deploy(sudo_user='custom-erp'))

        self.assertNotEqual(self._git('rev-parse', 'HEAD').strip(), self.previous_head)
        self.assertEqual(self._git('show', 'HEAD:message.txt'), 'after\n')
        self.assertEqual(
            self._git('log', '-1', '--format=%s').strip(),
            'https://github.com/gisce/erp/pull/42.diff',
        )
        self.assertEqual([state for state, details in self.statuses], ['pending', 'success'])
        self.assertTrue(any('Deploy success' in message for message in self.messages))
        self.assertTrue(all(user == 'custom-erp' for command, user in self.commands
                            if command.startswith(('test ', 'git '))))

    def test_missing_diff_is_an_error(self):
        os.unlink(os.path.join(self.checkout, self.diff_path))

        self.assertFalse(self._deploy())

        self._assert_failure('Checking that the remote diff exists failed (exit 1)')
        self.assertEqual(self._git('rev-parse', 'HEAD').strip(), self.previous_head)

    def test_unreadable_diff_preserves_remote_diagnostic(self):
        self.overrides['test -r ' + self.diff_path] = RemoteResult('Permission denied', 1)

        self.assertFalse(self._deploy())

        self._assert_failure('Permission denied')
        self.assertIn('test -r ' + self.diff_path, self.statuses[-1][1]['description'])

    def test_unicode_application_error_is_preserved(self):
        diagnostic = u"No s'ha pogut aplicar el pedaç"
        self.overrides['git apply ' + self.diff_path] = RemoteResult(diagnostic, 1)

        self.assertFalse(self._deploy())

        self._assert_failure("No s'ha pogut aplicar")
        self.assertIn(diagnostic, self.statuses[-1][1]['description'])
        logged_diagnostic = 'peda\\xe7' if six.PY2 else u'pedaç'
        self.assertIn(logged_diagnostic, self.error_stream.getvalue())

    def test_utf8_remote_output_is_decoded_before_formatting(self):
        diagnostic = u"Error: no s'ha pogut aplicar el pedaç"
        self.overrides['git apply ' + self.diff_path] = RemoteBytesResult(
            diagnostic.encode('utf-8'), 1
        )

        self.assertFalse(self._deploy())

        self._assert_failure("no s'ha pogut aplicar")
        self.assertIn(diagnostic, self.statuses[-1][1]['description'])
        logged_diagnostic = 'peda\\xe7' if six.PY2 else u'pedaç'
        self.assertIn(logged_diagnostic, self.error_stream.getvalue())

    def test_empty_diff_is_an_error(self):
        self._write(self.diff_path, '')

        self.assertFalse(self._deploy())

        self._assert_failure('Checking that the remote diff is not empty failed (exit 1)')

    def test_conflicting_diff_shows_git_apply_error(self):
        self._write('message.txt', 'conflicting change\n')
        self._git('add', 'message.txt')
        self._git('commit', '-q', '-m', 'Conflicting commit')

        self.assertFalse(self._deploy())

        self._assert_failure('patch does not apply')
        self.assertIn('Command: git apply ' + self.diff_path, self.statuses[-1][1]['description'])

    def _create_conflicting_commit(self):
        self._write('message.txt', 'conflicting change\n')
        self._git('add', 'message.txt')
        self._git('commit', '-q', '-m', 'Conflicting commit')

    def test_unresolved_rejects_cannot_be_committed(self):
        self._create_conflicting_commit()

        self.assertFalse(self._deploy(reject=True))

        self._assert_failure('Unresolved rejected hunks')
        self.assertTrue(os.path.isfile(os.path.join(self.checkout, 'message.txt.rej')))

    def test_manually_resolved_and_staged_rejects_are_committed(self):
        self._create_conflicting_commit()

        def resolve(message):
            self._write('message.txt', 'after\n')
            os.unlink(os.path.join(self.checkout, 'message.txt.rej'))
            self._git('add', 'message.txt')

        fabfile.prompt = resolve

        self.assertTrue(self._deploy(reject=True))

        self.assertEqual(self._git('show', 'HEAD:message.txt'), 'after\n')
        self.assertEqual(self._git('log', '-1', '--format=%s').strip(),
                         'https://github.com/gisce/erp/pull/42.diff')
        self.assertEqual(self._git('status', '--porcelain').strip(), '')

    def test_reject_resolution_without_changes_is_an_error(self):
        self._create_conflicting_commit()

        def discard(message):
            os.unlink(os.path.join(self.checkout, 'message.txt.rej'))

        fabfile.prompt = discard

        self.assertFalse(self._deploy(reject=True))

        self._assert_failure('produced no changes; no commit was created')

    def test_failed_commit_is_an_error_even_with_warn_only(self):
        self._write('.git/hooks/pre-commit', "#!/bin/sh\necho 'blocked by pre-commit' >&2\nexit 1\n")
        os.chmod(os.path.join(self.checkout, '.git/hooks/pre-commit'), 0o755)
        env.warn_only = True

        self.assertFalse(self._deploy())

        self._assert_failure('blocked by pre-commit')
        self.assertIn('Command: git commit -m ', self.statuses[-1][1]['description'])
        self.assertEqual(self._git('rev-parse', 'HEAD').strip(), self.previous_head)
        self.assertEqual(self._git('diff', '--cached', '--name-only').strip(), 'message.txt')

    def test_failed_git_add_is_an_error(self):
        self._write('.git/index.lock', '')

        self.assertFalse(self._deploy())

        self._assert_failure('index.lock')
        self.assertIn('Command: git add -A', self.statuses[-1][1]['description'])
        self.assertEqual(self._git('rev-parse', 'HEAD').strip(), self.previous_head)

    def test_successful_command_without_a_new_commit_is_an_error(self):
        self.overrides['git commit -m https://github.com/gisce/erp/pull/42.diff'] = RemoteResult('')

        self.assertFalse(self._deploy())

        self._assert_failure('No commit was created')
        self.assertEqual(self._git('rev-parse', 'HEAD').strip(), self.previous_head)

    def test_staged_work_is_stashed_and_excluded_from_the_pr_commit(self):
        self._write('local-only.txt', 'local work\n')
        self._git('add', 'local-only.txt')

        self.assertTrue(self._deploy())

        self.assertEqual(self._git('diff-tree', '--no-commit-id', '--name-only', '-r', 'HEAD').strip(),
                         'message.txt')
        with io.open(os.path.join(self.checkout, 'local-only.txt'), encoding='utf-8') as stream:
            self.assertEqual(stream.read(), 'local work\n')
        self.assertIn('local-only.txt', self._git('status', '--porcelain'))
        self.assertEqual(env.sudo_prefix, self.old_environment['sudo_prefix'])

    def test_failed_stash_restores_sudo_prefix_and_stops_deployment(self):
        self._write('message.txt', 'local work\n')
        self.overrides['git stash -u'] = RemoteResult('Cannot save local changes', 1)

        self.assertFalse(self._deploy())

        self._assert_failure('Cannot save local changes')
        self.assertFalse(any(command.startswith('git apply') for command, user in self.commands))

    def test_failed_stash_pop_stops_deployment_and_restores_sudo_prefix(self):
        self._write('local-only.txt', 'local work\n')
        self.overrides['git stash pop'] = RemoteResult('Could not restore local changes', 1)

        self.assertFalse(self._deploy())

        self._assert_failure('Could not restore local changes')
        self.assertIn('stash@{0}', self._git('stash', 'list'))

    def test_failed_stash_pop_does_not_hide_the_application_error(self):
        self._write('local-only.txt', 'local work\n')
        self.overrides['git apply ' + self.diff_path] = RemoteResult('Original application error', 1)
        self.overrides['git stash pop'] = RemoteResult('Stash restoration error', 1)

        self.assertFalse(self._deploy())

        self._assert_failure('Original application error')
        self.assertTrue(any('Stash restoration error' in message for message in self.messages))

    def test_status_reporting_failure_does_not_hide_the_git_error(self):
        self._write(self.diff_path, '')

        def failed_status(deploy_id, state='success', **kwargs):
            self._mark_status(deploy_id, state, **kwargs)
            if state == 'error':
                raise RuntimeError('GitHub status unavailable')

        fabfile.mark_deploy_status = failed_status

        self.assertFalse(self._deploy())

        self._assert_failure('Checking that the remote diff is not empty failed')
        self.assertIn('GitHub status unavailable', self.error_stream.getvalue())


class GithubDeploymentStatusTest(unittest.TestCase):
    def setUp(self):
        self.old_post = fabfile.requests.post
        self.old_config = fabfile.github_config
        self.calls = []
        self.response = requests.Response()
        self.response.status_code = 201
        self.response.url = 'https://api.github.com/repos/gisce/erp/deployments/123/statuses'
        fabfile.requests.post = self._post
        fabfile.github_config = lambda: {'token': 'test-token'}

    def tearDown(self):
        fabfile.requests.post = self.old_post
        fabfile.github_config = self.old_config

    def _post(self, url, data, headers):
        self.calls.append((url, json.loads(data)))
        return self.response

    def test_long_error_descriptions_fit_the_github_limit(self):
        diagnostic = 'Remote command failed: ' + 'x' * 200

        fabfile.mark_deploy_status(123, state='error', description=diagnostic)

        self.assertEqual(self.calls[0][1]['description'], diagnostic[:140])
        self.assertEqual(self.calls[0][1]['state'], 'error')

    def test_rejected_deployment_status_raises_and_does_not_label_the_pr(self):
        self.response.status_code = 422

        with self.assertRaises(requests.HTTPError):
            fabfile.mark_deploy_status(123, state='success', pr_number='42')

        self.assertEqual(len(self.calls), 1)


class RemoteConsoleOutputTest(unittest.TestCase):
    def test_error_and_progress_messages_are_written_as_utf8(self):
        stream = io.BytesIO() if six.PY2 else io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = stream
            fabfile._print_message(u'\u26d4 Error applying pedaç')
            fabfile._tqdm_write(u'Deploy failure \U0001f680')
        finally:
            sys.stdout = old_stdout

        output = stream.getvalue()
        if not isinstance(output, six.text_type):
            output = output.decode('utf-8')
        self.assertIn(u'\u26d4 Error applying pedaç', output)
        self.assertIn(u'Deploy failure \U0001f680', output)


if __name__ == '__main__':
    unittest.main()
