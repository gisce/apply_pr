# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import os
import io
import logging
import shutil
import subprocess
import sys
import tempfile
import unittest

import six

from apply_pr import local


class FakeBackend(object):
    def __init__(self, patch_path):
        self.patch_path = patch_path
        self.statuses = []
        self.deployments = []

    def mark_to_deploy(
        self, pr_number, hostname=False, owner='gisce', repository='erp'
    ):
        self.deployments.append((pr_number, hostname, owner, repository))
        return 123

    def mark_deploy_status(self, deploy_id, state='success', **kwargs):
        self.statuses.append((deploy_id, state, kwargs))

    def export_patches_from_github(
        self, pr_number, from_commit=None, owner='gisce', repository='erp'
    ):
        destination = os.path.join(
            'deploy', 'patches', str(pr_number)
        )
        os.makedirs(destination)
        shutil.copy(
            self.patch_path,
            os.path.join(destination, os.path.basename(self.patch_path)),
        )


class LocalDeploymentTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix='apply-pr-test-')
        self.src = os.path.join(self.tempdir, 'src')
        self.checkout = os.path.join(self.src, 'erp')
        os.makedirs(self.checkout)
        self._git('init', '-q')
        self._git('config', 'user.name', 'Sastre Test')
        self._git('config', 'user.email', 'sastre@example.net')
        self._git('checkout', '-q', '-b', 'rolling')
        self._write('message.txt', 'before\n')
        self._git('add', 'message.txt')
        self._git('commit', '-q', '-m', 'Initial commit')
        self.patch_path = self._create_patch()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def _git(self, *arguments):
        output = subprocess.check_output(
            ['git'] + list(arguments),
            cwd=self.checkout,
            stderr=subprocess.STDOUT,
        )
        return output.decode('utf-8', 'replace')

    def _write(self, path, value):
        with open(os.path.join(self.checkout, path), 'w') as stream:
            stream.write(value)

    def _create_patch(self):
        self._write('message.txt', 'after\n')
        self._git('add', 'message.txt')
        self._git('commit', '-q', '-m', 'Change greeting')
        patch = subprocess.check_output(
            ['git', 'format-patch', '-1', '--stdout'],
            cwd=self.checkout,
            stderr=subprocess.STDOUT,
        )
        patch_path = os.path.join(
            self.tempdir, '0001-change-greeting.patch'
        )
        with open(patch_path, 'wb') as stream:
            stream.write(patch)
        self._git('reset', '-q', '--hard', 'HEAD^')
        return patch_path

    def test_applies_patch_without_ssh_and_updates_deployment(self):
        backend = FakeBackend(self.patch_path)

        result = local.apply_pr(
            backend,
            '42',
            src=self.src,
            repository='erp',
            environment='test',
            auto_exit=True,
        )

        self.assertTrue(result)
        with open(os.path.join(self.checkout, 'message.txt')) as stream:
            self.assertEqual(stream.read(), 'after\n')
        self.assertEqual(self._git('log', '-1', '--format=%s').strip(),
                         'Change greeting')
        self.assertEqual(
            [status[1] for status in backend.statuses],
            ['pending', 'success'],
        )

    def test_rejects_dirty_checkout_before_registering_deployment(self):
        backend = FakeBackend(self.patch_path)
        self._write('message.txt', 'dirty\n')

        result = local.apply_pr(
            backend,
            '42',
            src=self.src,
            repository='erp',
            auto_exit=True,
        )

        self.assertFalse(result)
        self.assertEqual(backend.deployments, [])

    def test_requires_rolling_branch_by_default(self):
        backend = FakeBackend(self.patch_path)
        self._git('checkout', '-q', '-b', 'feature')

        result = local.apply_pr(
            backend,
            '42',
            src=self.src,
            repository='erp',
            auto_exit=True,
        )

        self.assertFalse(result)
        self.assertEqual(backend.deployments, [])

    def test_uses_the_same_progress_messages_as_remote_deploy(self):
        messages = []
        updates = []

        class FakeTqdm(object):
            def __init__(self, total=None, desc=None):
                self.total = total
                self.desc = desc

            @staticmethod
            def write(message):
                messages.append(local._as_text(message))

            def update(self, amount=1):
                updates.append(amount)

            def close(self):
                pass

        class FakeColors(object):
            blue = staticmethod(lambda message: message)
            green = staticmethod(lambda message: message)
            magenta = staticmethod(lambda message: message)
            red = staticmethod(lambda message: message)
            yellow = staticmethod(lambda message: message)

        backend = FakeBackend(self.patch_path)
        old_tqdm = local.tqdm
        old_colors = local.colors
        try:
            local.tqdm = FakeTqdm
            local.colors = FakeColors
            result = local.apply_pr(
                backend,
                '42',
                src=self.src,
                repository='erp',
                auto_exit=True,
            )
        finally:
            local.tqdm = old_tqdm
            local.colors = old_colors

        self.assertTrue(result)
        self.assertIn(u'Marking to deploy (123) \U0001F680', messages)
        self.assertIn(u'Applying patches \U0001F648', messages)
        self.assertIn(u'Applying: Change greeting', messages)
        self.assertIn(u'Deploy success \U0001F680', messages)
        self.assertEqual(updates, [1])


class UnicodeLoggingTest(unittest.TestCase):
    def test_logs_unicode_exception_without_ascii_encoding_error(self):
        class LoggingCapture(object):
            encoding = 'utf-8'

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

        stream = LoggingCapture()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(
            str('%(levelname)s:%(name)s:%(message)s')
        ))
        old_handlers = local.logger.handlers[:]
        old_level = local.logger.level
        old_propagate = local.logger.propagate
        try:
            local.logger.handlers = [handler]
            local.logger.setLevel(logging.ERROR)
            local.logger.propagate = False

            local._log_error(
                local.LocalApplyError(u"No s'ha pogut aplicar el pedaç")
            )
        finally:
            local.logger.handlers = old_handlers
            local.logger.setLevel(old_level)
            local.logger.propagate = old_propagate

        output = stream.getvalue()
        if six.PY2:
            self.assertIn(u'peda\\xe7', output)
        else:
            self.assertIn(u'pedaç', output)

    def test_prints_unicode_message_as_utf8(self):
        if six.PY2:
            stream = io.BytesIO()
        else:
            stream = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = stream
            local._print_message(u"No s'ha pogut aplicar el pedaç")
        finally:
            sys.stdout = old_stdout

        output = stream.getvalue()
        if not isinstance(output, six.text_type):
            output = output.decode('utf-8')
        self.assertIn(u'pedaç', output)


if __name__ == '__main__':
    unittest.main()
