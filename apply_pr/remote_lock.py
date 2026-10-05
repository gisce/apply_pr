# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import hashlib
import json
import pipes

import six


class RepositoryLocked(Exception):
    pass


class RemoteRepositoryLock(object):
    """Hold an advisory lock on a dedicated SSH channel."""

    lock_directory = '/tmp/apply_pr-locks'

    def __init__(self, common_directory, client, host_string, pr_number=None):
        self.common_directory = common_directory
        self.client = client
        self.host_string = host_string
        self.pr_number = pr_number
        self.channel = None

    def _lock_path(self):
        digest = hashlib.sha256(
            self.common_directory.encode('utf-8')
        ).hexdigest()
        return '{}/{}.lock'.format(self.lock_directory, digest)

    def acquire(self):
        lock_path = self._lock_path()
        self.channel = self.client.get_transport().open_session()
        metadata = json.dumps({
            'host': self.host_string,
            'pr': self.pr_number,
            'repository': self.common_directory,
        }, sort_keys=True)
        command = (
            'mkdir -m 1777 -p {directory} && exec flock -n {lock} sh -c '
            '{script} sh {lock} {metadata}'
        ).format(
            directory=pipes.quote(self.lock_directory),
            lock=pipes.quote(lock_path),
            script=pipes.quote(
                'printf "%s\\n" "$2" > "$1"; '
                'printf "APPLY_PR_LOCKED\\n"; cat >/dev/null'
            ),
            metadata=pipes.quote(metadata),
        )
        self.channel.exec_command(command)
        marker = self.channel.makefile('r').readline().strip()
        if not isinstance(marker, six.text_type):
            marker = marker.decode('utf-8')
        if marker != 'APPLY_PR_LOCKED':
            self.channel.close()
            self.channel = None
            raise RepositoryLocked(
                'Repository {} is already being modified by another '
                'apply_pr process ({})'.format(
                    self.common_directory, lock_path
                )
            )
        return self

    def release(self):
        if self.channel is not None:
            self.channel.close()
            self.channel = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
