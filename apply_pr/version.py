# coding=utf-8
from __future__ import unicode_literals
from pkg_resources import parse_version

import requests


def check_version():
    import apply_pr
    running_version = apply_pr.__version__
    last_version = latest_version()
    if parse_version(running_version) < parse_version(latest_version()):
        raise SystemExit('Your version {} is outdated. Upgrade to {}'.format(
            running_version, last_version
        ))


def available_versions():
    r = requests.get('https://pypi.python.org/pypi/apply_pr/json')
    return sorted(r.json()['releases'].keys(), key=parse_version)


def latest_version():
    return available_versions()[-1]