# -*- coding: utf-8 -*-
from __future__ import (
    with_statement, absolute_import, unicode_literals, print_function
)

import time
import os
import logging
import qrcode
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

    res = config_from_environment('GITHUB', **config)
    if 'token' not in res:
        token = oauth_login()
        if token:
            res['token'] = token
            os.environ['GITHUB_TOKEN'] = token
    validate(res)
    return res


def oauth_login():
    CLIENT_ID = "Ov23li0hFOB6BrHDUCHJ"
    device_code_response = requests.post(
        "https://github.com/login/device/code",
        data={
            "client_id": CLIENT_ID,
            "scope": "repo read:project read:user"
        },
        headers={"Accept": "application/json"}
    )

    device_code_data = device_code_response.json()
    user_code = device_code_data["user_code"]
    verification_uri = device_code_data["verification_uri"]
    device_code = device_code_data["device_code"]
    interval = device_code_data["interval"]

    print("\nTo authorize this script, follow these steps:")
    print("1. Visit this link in your browser: {}".format(verification_uri))
    print("2. Enter this code: {} \ud83d\udd10\n".format(user_code))

    qr = qrcode.QRCode()
    qr.add_data(verification_uri)
    qr.make()
    qr.print_ascii(invert=True)

    token = None
    while True:
        time.sleep(interval)
        token_response = requests.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code"
            },
            headers={"Accept": "application/json"}
        )

        response_data = token_response.json()

        if "access_token" in response_data:
            token = response_data["access_token"]
            print("\n\u2705 Authentication successful!")
            break
        elif response_data.get("error") == "authorization_pending":
            print("\u23f3 Waiting for authorization...")

        elif response_data.get("error") == "slow_down":
            interval += 5  # Reduce polling frequency if GitHub requests it
        else:
            print("\u274c Error: {}".format(
                response_data.get('error_description', 'Unknown error')))
            break

    if token:
        headers = {"Authorization": "token {}".format(token)}
        user_info = requests.get("https://api.github.com/user", headers=headers)
        user_data = user_info.json()
        print(
            "\n\ud83d\udc4b Welcome, {}!".format(
                user_data['login']))
    return token
