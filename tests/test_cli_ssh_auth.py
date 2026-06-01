# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import os
import stat
import sys
import types
import unittest


class DummyEnv(object):
    pass


fake_env = DummyEnv()

fake_fabric = types.ModuleType(str('fabric'))
fake_fabric_tasks = types.ModuleType(str('fabric.tasks'))
fake_fabric_api = types.ModuleType(str('fabric.api'))
fake_fabric_colors = types.ModuleType(str('fabric.colors'))

fake_fabric_tasks.execute = lambda *args, **kwargs: {}
fake_fabric_tasks.WrappedCallableTask = lambda task: task
fake_fabric_api.env = fake_env
fake_fabric_colors.red = lambda text: text
fake_fabric_colors.yellow = lambda text: text
fake_fabric_colors.green = lambda text: text
fake_fabric.tasks = fake_fabric_tasks
fake_fabric.api = fake_fabric_api
fake_fabric.colors = fake_fabric_colors

sys.modules.setdefault('fabric', fake_fabric)
sys.modules.setdefault('fabric.tasks', fake_fabric_tasks)
sys.modules.setdefault('fabric.api', fake_fabric_api)
sys.modules.setdefault('fabric.colors', fake_fabric_colors)

import apply_pr.cli as cli


class ConfigureSSHAuthTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop('SSH_PRIVATE_KEY', None)
        os.environ.pop('SSH_PRIVATE_KEY_FILE', None)
        cli.cleanup_ssh_private_key_file()
        fake_env.__dict__.clear()

    def tearDown(self):
        os.environ.pop('SSH_PRIVATE_KEY', None)
        os.environ.pop('SSH_PRIVATE_KEY_FILE', None)
        cli.cleanup_ssh_private_key_file()
        fake_env.__dict__.clear()

    def test_enables_ssh_config_without_private_key(self):
        cli.configure_ssh_auth()

        self.assertTrue(fake_env.use_ssh_config)
        self.assertFalse(hasattr(fake_env, 'key_filename'))

    def test_uses_ssh_private_key_file_when_configured(self):
        os.environ['SSH_PRIVATE_KEY_FILE'] = '/tmp/sastre_id_rsa'

        cli.configure_ssh_auth()

        self.assertTrue(fake_env.use_ssh_config)
        self.assertEqual(fake_env.key_filename, '/tmp/sastre_id_rsa')

    def test_writes_ssh_private_key_to_restricted_temp_file(self):
        os.environ['SSH_PRIVATE_KEY'] = '-----BEGIN TEST KEY-----\nabc\n-----END TEST KEY-----'

        cli.configure_ssh_auth()

        key_filename = fake_env.key_filename
        self.assertTrue(os.path.exists(key_filename))
        file_mode = stat.S_IMODE(os.stat(key_filename).st_mode)
        self.assertEqual(file_mode, stat.S_IRUSR | stat.S_IWUSR)
        with open(key_filename, 'rb') as key_file:
            key_contents = key_file.read()
        self.assertEqual(
            key_contents,
            b'-----BEGIN TEST KEY-----\nabc\n-----END TEST KEY-----\n'
        )

        cli.cleanup_ssh_private_key_file()
        self.assertFalse(os.path.exists(key_filename))


if __name__ == '__main__':
    unittest.main()
