# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import os
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
        os.environ.pop('APPLY_PR_SSH_KEY_PATH', None)
        fake_env.__dict__.clear()

    def tearDown(self):
        os.environ.pop('APPLY_PR_SSH_KEY_PATH', None)
        fake_env.__dict__.clear()

    def test_enables_ssh_config_without_private_key(self):
        cli.configure_ssh_auth()

        self.assertTrue(fake_env.use_ssh_config)
        self.assertFalse(hasattr(fake_env, 'key_filename'))
        self.assertFalse(hasattr(fake_env, 'gateway'))

    def test_uses_apply_pr_ssh_key_path_when_configured(self):
        os.environ['APPLY_PR_SSH_KEY_PATH'] = '/tmp/sastre_id_rsa'

        cli.configure_ssh_auth()

        self.assertTrue(fake_env.use_ssh_config)
        self.assertEqual(fake_env.key_filename, '/tmp/sastre_id_rsa')

    def test_uses_proxy_as_ssh_gateway_when_configured(self):
        cli.configure_ssh_auth(proxy='gisce@proxy.example.net')

        self.assertTrue(fake_env.use_ssh_config)
        self.assertEqual(fake_env.gateway, 'gisce@proxy.example.net')


if __name__ == '__main__':
    unittest.main()
