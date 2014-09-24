from __future__ import with_statement
import json
import logging
import os

from fabric.api import local, run, cd, put, settings, abort, sudo, hide
import requests


log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)


def get_token():
    return os.environ.get('GITHUB_TOKEN', '')


def upload_patches(name):
    remote_dir = '~/src/erp/patches/%s' % name
    with settings(sudo_user='erp'):
        run("mkdir -p %s" % remote_dir)
        put('deploy/patches/%s/*.patch' % name, remote_dir)


def apply_remote_patches(name, from_patch=0):
    from_patch = int(from_patch)
    with settings(warn_only=True, sudo_user='erp'):
        with hide('output'):
            patches = sudo("ls -1 /home/erp/src/erp/patches/%s/*.patch" % name)
        for patch in patches.split():
            number = int(os.path.basename(patch).split('-')[0])
            if number < from_patch:
                logger.info('Skipping patch %s' % patch)
                continue
            with cd("/home/erp/src/erp"):
                result = sudo("git am %s" % patch)
                if result.failed:
                    logger.error('Applying patches for version %s failed' % name)
                    with cd('/home/erp/src/erp'):
                        sudo("git am --abort")
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
    branch = pull['head']['label'].split(':')[1]
    logger.info('Commits: %s..%s (%s)' % (from_commit, to_commit, branch))
    return from_commit, to_commit, branch


def export_patches(from_commit, to_commit, name):
    logger.info('Exporting patches from %s to %s' % (from_commit, to_commit))
    local("mkdir -p deploy/patches/%s" % name)
    local("git format-patch -o deploy/patches/%s %s..%s" % (
        name, from_commit, to_commit)
    )


def mark_to_deploy(pr_number):
    logger.info('Marking as deployed on GitHub')
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % get_token()
    }
    commit = find_from_to_commits(pr_number)[2]
    host = run("uname -n")
    payload = {
        'ref': commit, 'task': 'deploy', 'auto_merge': False,
        'environment': host, 'description': host,
        'payload': {
            'host': host
        }
    }
    url = "https://api.github.com/repos/gisce/erp/deployments"
    r = requests.post(url, data=json.dumps(payload), headers=headers)
    res = json.loads(r.text)
    deploy_id = res['id']
    logger.info('Deploy id: %s' % deploy_id)
    return deploy_id


def mark_deploy_status(deploy_id, state='success'):
    logger.info('Marking as deployed %s on GitHub' % state)
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % get_token()
    }

    url = "https://api.github.com/repos/gisce/erp/deployments/%s/statuses"
    payload = {'state': state}
    r = requests.post(url % deploy_id, data=json.dumps(payload),
                      headers=headers)
    logger.info('Deploy %s marked as %s' % (deploy_id, state))


def export_patches_pr(pr_number):
    from_commit, to_commit, branch = find_from_to_commits(pr_number)
    export_patches(from_commit, to_commit, pr_number)


def export_remote_patches(pr_number):
    from_commit, to_commit, branch = find_from_to_commits(pr_number)
    with settings(sudo_user='erp'):
        logger.info('Exporting patches from %s to %s' % (from_commit, to_commit))
        sudo("mkdir -p /home/erp/src/erp/patches/%s" % pr_number)
        with cd("/home/erp/src/erp"):
            sudo("git fetch origin")
        with cd("/home/erp/src/erp"):
            sudo("git format-patch -o patches/%s origin/%s %s..%s" % (
                pr_number, branch, from_commit, to_commit)
            )


def check_is_rolling():
    with settings(hide('everything'), sudo_user='erp', warn_only=True):
        with cd("/home/erp/src/erp"):
            res = sudo("git branch | grep '* rolling'")
            if res.return_code:
                abort("The repository is not in rolling mode")


def apply_pr(pr_number, from_number=0):
    check_is_rolling()
    deploy_id = mark_to_deploy(pr_number)
    mark_deploy_status(deploy_id, 'pending')
    export_remote_patches(pr_number)
    apply_remote_patches(pr_number, from_number)
    mark_deploy_status(deploy_id, 'success')
