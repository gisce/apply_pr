# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import unittest
import shutil
import subprocess
import tempfile

from apply_pr.remote_lock import RemoteRepositoryLock, RepositoryLocked


class FakeStream(object):
    def __init__(self, line):
        self.line = line

    def readline(self):
        return self.line


class FakeChannel(object):
    def __init__(self, line='APPLY_PR_LOCKED\n'):
        self.line = line
        self.command = None
        self.closed = False

    def exec_command(self, command):
        self.command = command

    def makefile(self, mode):
        return FakeStream(self.line)

    def close(self):
        self.closed = True


class FakeTransport(object):
    def __init__(self, channel):
        self.channel = channel

    def open_session(self):
        return self.channel


class FakeClient(object):
    def __init__(self, channel):
        self.channel = channel

    def get_transport(self):
        return FakeTransport(self.channel)


class LocalChannel(object):
    def exec_command(self, command):
        self.process = subprocess.Popen(
            command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )

    def makefile(self, mode):
        self.stdout = self.process.stdout
        return self.stdout

    def close(self):
        self.process.stdin.close()
        self.process.wait()
        self.stdout.close()


class LocalTransport(object):
    def open_session(self):
        return LocalChannel()


class LocalClient(object):
    def get_transport(self):
        return LocalTransport()


class RemoteRepositoryLockTest(unittest.TestCase):
    def setUp(self):
        self.host_string = 'deployer@example.net'

    def _lock(self, channel):
        return RemoteRepositoryLock(
            '/srv/src/erp/.git', FakeClient(channel), self.host_string,
            pr_number='178',
        )

    def test_holds_lock_on_dedicated_channel_until_release(self):
        channel = FakeChannel()
        lock = self._lock(channel)

        lock.acquire()

        self.assertFalse(channel.closed)
        self.assertIn('flock -n', channel.command)
        self.assertIn('178', channel.command)
        lock.release()
        self.assertTrue(channel.closed)

    def test_reports_contention_and_closes_failed_channel(self):
        channel = FakeChannel(line='')
        lock = self._lock(channel)

        with self.assertRaises(RepositoryLocked):
            lock.acquire()

        self.assertTrue(channel.closed)

    def test_context_manager_releases_lock_after_exception(self):
        channel = FakeChannel()
        lock = self._lock(channel)

        with self.assertRaises(RuntimeError):
            with lock:
                raise RuntimeError('deployment failed')

        self.assertTrue(channel.closed)

    def test_real_flock_excludes_concurrent_process_and_is_reusable(self):
        lock_directory = tempfile.mkdtemp(prefix='apply-pr-lock-test-')
        try:
            first = RemoteRepositoryLock(
                '/srv/src/erp/.git', LocalClient(), self.host_string, '178'
            )
            second = RemoteRepositoryLock(
                '/srv/src/erp/.git', LocalClient(), self.host_string, '179'
            )
            first.lock_directory = lock_directory
            second.lock_directory = lock_directory

            first.acquire()
            with self.assertRaises(RepositoryLocked):
                second.acquire()
            first.release()
            second.acquire()
            second.release()
        finally:
            shutil.rmtree(lock_directory)


if __name__ == '__main__':
    unittest.main()
