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
import apply_pr.local as local_backend
import apply_pr as apply_pr_package


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


class DeploymentTargetValidationTest(unittest.TestCase):
    def test_remote_mode_requires_host(self):
        with self.assertRaises(cli.click.UsageError):
            cli.validate_deployment_target()

    def test_local_mode_does_not_require_host(self):
        cli.validate_deployment_target(local_mode=True)

    def test_local_mode_rejects_host(self):
        with self.assertRaises(cli.click.UsageError):
            cli.validate_deployment_target(
                local_mode=True, host='erp.example.net'
            )

    def test_local_mode_rejects_ssh_proxy(self):
        with self.assertRaises(cli.click.UsageError):
            cli.validate_deployment_target(
                local_mode=True, proxy='proxy.example.net'
            )

    def test_local_mode_bypasses_fabric_execute_and_ssh_configuration(self):
        calls = []
        fake_fabfile = types.ModuleType(str('apply_pr.fabfile'))
        old_fabfile = sys.modules.get('apply_pr.fabfile')
        old_package_fabfile = getattr(
            apply_pr_package, 'fabfile', None
        )
        old_local_apply = local_backend.apply_pr
        old_execute = cli.execute
        old_configure_ssh_auth = cli.configure_ssh_auth

        def fake_local_apply(backend, pr_number, **kwargs):
            calls.append((backend, pr_number, kwargs))
            return True

        def forbidden(*args, **kwargs):
            raise AssertionError('SSH/Fabric remote execution was used')

        try:
            sys.modules['apply_pr.fabfile'] = fake_fabfile
            apply_pr_package.fabfile = fake_fabfile
            local_backend.apply_pr = fake_local_apply
            cli.execute = forbidden
            cli.configure_ssh_auth = forbidden

            result = cli.apply_pr(
                '42',
                local_mode=True,
                src='/srv/src',
                repository='erp',
                environ='test',
            )
        finally:
            local_backend.apply_pr = old_local_apply
            cli.execute = old_execute
            cli.configure_ssh_auth = old_configure_ssh_auth
            if old_fabfile is None:
                sys.modules.pop('apply_pr.fabfile', None)
            else:
                sys.modules['apply_pr.fabfile'] = old_fabfile
            if old_package_fabfile is None:
                delattr(apply_pr_package, 'fabfile')
            else:
                apply_pr_package.fabfile = old_package_fabfile

        self.assertEqual(result, [{'local': True}])
        self.assertEqual(calls[0][0], fake_fabfile)
        self.assertEqual(calls[0][1], '42')


if __name__ == '__main__':
    unittest.main()
