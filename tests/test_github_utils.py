# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import io
import sys
import types
import unittest


class DummyQRCode(object):
    def add_data(self, data):
        pass

    def make(self):
        pass

    def print_ascii(self, invert=True):
        pass


fake_qrcode = types.ModuleType(str('qrcode'))
fake_qrcode.QRCode = DummyQRCode
sys.modules.setdefault('qrcode', fake_qrcode)

fake_osconf = types.ModuleType(str('osconf'))
fake_osconf.config_from_environment = lambda prefix, **config: config
sys.modules.setdefault('osconf', fake_osconf)

fake_importlib_metadata = types.ModuleType(str('importlib_metadata'))
fake_importlib_metadata.version = lambda package: 'unknown'
sys.modules.setdefault('importlib_metadata', fake_importlib_metadata)

import apply_pr.github_utils as github_utils


class DummyResponse(object):
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


class OAuthLoginEncodingTest(unittest.TestCase):
    def test_success_message_uses_valid_unicode_codepoints(self):
        calls = []

        def fake_post(url, data=None, headers=None):
            calls.append(url)
            if url.endswith('/device/code'):
                return DummyResponse({
                    'user_code': 'ABCD-1234',
                    'verification_uri': 'https://github.com/login/device',
                    'device_code': 'device-code',
                    'interval': 0,
                })
            return DummyResponse({'access_token': 'token-value'})

        def fake_get(url, headers=None):
            return DummyResponse({'login': 'ecarreras'})

        old_post = github_utils.requests.post
        old_get = github_utils.requests.get
        old_qrcode = github_utils.qrcode.QRCode
        old_sleep = github_utils.time.sleep
        old_stdout = sys.stdout
        output = io.StringIO()
        try:
            github_utils.requests.post = fake_post
            github_utils.requests.get = fake_get
            github_utils.qrcode.QRCode = DummyQRCode
            github_utils.time.sleep = lambda interval: None
            sys.stdout = output

            token = github_utils.oauth_login()
        finally:
            github_utils.requests.post = old_post
            github_utils.requests.get = old_get
            github_utils.qrcode.QRCode = old_qrcode
            github_utils.time.sleep = old_sleep
            sys.stdout = old_stdout

        self.assertEqual(token, 'token-value')
        text = output.getvalue()
        self.assertIn('Welcome, ecarreras!', text)
        text.encode('utf-8')
        self.assertNotIn('\ud83d', text)
        self.assertNotIn('\udc4b', text)


if __name__ == '__main__':
    unittest.main()
