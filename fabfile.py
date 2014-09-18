from __future__ import with_statement
import json
import logging
import os

from fabric.api import local, run, cd, put, settings, abort
import requests


log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)


def get_token():
    return os.environ.get('GITHUB_TOKEN', '')

def export_patches(from_commit, to_commit, name):
    logger.info('Exporting patches from %s to %s' % (from_commit, to_commit))
    local("mkdir -p deploy/patches/%s" % name)
    local("git format-patch -o deploy/patches/%s %s..%s" % (
        name, from_commit, to_commit)
    )


def upload_patches(name):
    remote_dir = '~/src/erp/patches/%s' % name
    run("mkdir -p %s" % remote_dir)
    put('deploy/patches/%s/*.patch' % name, remote_dir)


def apply_remote_patches(name, from_patch=0):
    with settings(warn_only=True):
        patches = run("ls ~/src/erp/patches/%s/*.patch" % name)
        for patch in patches.split():
            number = int(os.path.basename(patch).split('-')[0])
            if number < from_patch:
                continue
            result = run("git am %s" % patch)
            if result.failed:
                logger.error('Applying patches for version %s failed' % name)
                with cd('~/src/erp'):
                    run("git am --abort")
                abort('Aborting due patch number %s not apply' % number)


def find_from_to_commits(pr_number):
    headers = {'Authorization': 'token %s' % get_token()}
    url = "https://api.github.com/repos/gisce/erp/pulls/%s" % pr_number
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        abort("Unable to get info from the pull request")
    pull = json.loads(r.text)
    from_commit = pull['base']['sha']
    to_commit = pull['head']['sha']
    logger.info('Commits: %s..%s' % (from_commit, to_commit))
    return from_commit, to_commit


def export_patches_pr(pr_number):
    from_commit, to_commit = find_from_to_commits(pr_number)
    export_patches(from_commit, to_commit, pr_number)


def apply_pr(pr_number, from_number):
    export_patches_pr(pr_number)
    upload_patches(pr_number)
    apply_remote_patches(pr_number, from_number)