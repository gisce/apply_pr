# -*- coding: utf-8 -*-
from __future__ import (
    with_statement, absolute_import, unicode_literals, print_function
)
import requests

from osconf import config_from_environment
def is_github_token_valid(token):
    headers = {'Authorization': 'token {token}'.format(token=token)}
    url = "https://api.github.com/user"

    r = requests.get(url, headers=headers)

    return r.status_code == 200


def github_config(**config):
    def validate(_config):
        if 'token' not in _config or not _config['token']:
            raise EnvironmentError("GITHUB_TOKEN variable not provided")
        if not is_github_token_valid(_config['token']):
            raise EnvironmentError("GITHUB_TOKEN not valid or expired")

    res = config_from_environment('GITHUB', ['token'], **config)
    validate(res)
    return res
