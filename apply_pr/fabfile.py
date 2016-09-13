from __future__ import (
    with_statement, absolute_import, unicode_literals, print_function
)
import json
import logging
import os

from fabric.api import local, run, cd, put, settings, abort, sudo, hide, task
from fabric.operations import open_shell
from osconf import config_from_environment
from slugify import slugify
import requests
import StringIO
from collections import OrderedDict

logger = logging.getLogger(__name__)


def github_config(**config):
    return config_from_environment('GITHUB', ['token'], **config)


def apply_pr_config(**config):
    return config_from_environment('APPLY_PR', **config)


@task
def upload_patches(pr_number):
    temp_dir = '/tmp/%s' % pr_number
    remote_dir = '/home/erp/src/erp/patches/'
    sudo("mkdir -p %s" % remote_dir)
    sudo("mkdir -p %s" % temp_dir)
    put('deploy/patches/%s/*.patch' % pr_number, temp_dir, use_sudo=True)
    sudo("rm -rf %s/%s" % (remote_dir, pr_number))
    sudo("mv %s %s" % (temp_dir, remote_dir))
    sudo("chown -R erp: %s" % remote_dir)



@task
def apply_remote_patches(name, from_patch=0):
    from_patch = int(from_patch)
    with settings(warn_only=True, sudo_user='erp'):
        with hide('output'):
            patches = sudo("ls -1 /home/erp/src/erp/patches/%s/*.patch" % name)

        patches_to_apply = []
        for patch in patches.split():
            number = int(os.path.basename(patch).split('-')[0])
            if number < from_patch:
                logger.info('Skipping patch %s' % patch)
                continue
            patches_to_apply.append(patch)

        if patches_to_apply:
            patches_to_apply = ' '.join(patches_to_apply)
            with cd("/home/erp/src/erp"):
                result = sudo("git am %s" % patches_to_apply)
                git_skip_or_abort(result)


def git_skip_or_abort(result):
    if result.failed:
        logger.error(
            'Applying patches failed.. Skipping or aborting...'
        )
        skip_or_abort = raw_input('skip/abort/shell? ')
        while skip_or_abort not in ('skip', 'abort', 'shell'):
            skip_or_abort = raw_input('skip or abort? ')
        with cd('/home/erp/src/erp'):
            if skip_or_abort == 'shell':
                open_shell()
                return
            result = sudo("git am --{0}".format(skip_or_abort))
            git_skip_or_abort(result)
        if skip_or_abort == 'abort':
            abort('Aborting due some patch does not apply')


@task
def find_from_to_commits(pr_number):
    headers = {'Authorization': 'token %s' % github_config()['token']}
    url = "https://api.github.com/repos/gisce/erp/pulls/%s" % pr_number
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        abort("Unable to get info from the pull request")
    pull = json.loads(r.text)
    from_commit = pull['base']['sha']
    to_commit = pull['head']['sha']
    head_origin, head_branch = pull['head']['label'].split(':')
    base_origin, base_branch = pull['base']['label'].split(':')
    if head_origin != base_origin or pull['merged']:
        branch = None
    else:
        branch = head_branch
    logger.info('Commits: %s..%s (%s)' % (from_commit, to_commit, branch))
    return from_commit, to_commit, branch


@task
def export_patches_from_git(from_commit, to_commit, pr_number):
    logger.info('Exporting patches from %s to %s' % (from_commit, to_commit))
    local("mkdir -p deploy/patches/%s" % pr_number)
    local("git format-patch -o deploy/patches/%s %s..%s" % (
        pr_number, from_commit, to_commit)
    )


@task
def export_patches_from_github(pr_number):
    repo = github_config(repository='gisce/erp')['repository']
    patch_folder = "deploy/patches/%s" % pr_number
    local("mkdir -p %s" % patch_folder)
    logger.info('Exporting patches from GitHub')
    headers = {'Authorization': 'token %s' % github_config()['token']}
    # Pagination documentation: https://developer.github.com/v3/#pagination
    url = "https://api.github.com/repos/%s/pulls/%s/commits?per_page=100" \
          % (repo, pr_number)
    r = requests.get(url, headers=headers)
    commits = json.loads(r.text)
    patch_headers = headers.copy()
    patch_headers['Accept'] = 'application/vnd.github.patch'
    for idx, commit in enumerate(commits):
        if commit['commit']['message'].lower().startswith('merge'):
            logger.info('Skipping merge commit {sha}: {message}'.format(
                sha=commit['sha'], message=commit['commit']['message']
            ))
            continue
        r = requests.get(commit['url'], headers=patch_headers)
        message = slugify(commit['commit']['message'][:64])
        filename = '%04i-%s.patch' % (idx + 1, message)
        with open(os.path.join(patch_folder, filename), 'w') as patch:
            logger.info('Patch %s exported.' % filename)
            patch.write(r.text)


@task
def mark_to_deploy(pr_number):
    logger.info('Marking as deployed on GitHub')
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    url = "https://api.github.com/repos/gisce/erp/pulls/%s" % pr_number
    r = requests.get(url, headers=headers)
    pull = json.loads(r.text)
    commit = pull['head']['sha']
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
    if not 'id' in res:
        logger.info('Not marking deployment in github: %s' % res['message'])
        return 0
    deploy_id = res['id']
    logger.info('Deploy id: %s' % deploy_id)
    return deploy_id


@task
def get_deploys(pr_number):
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    url = "https://api.github.com/repos/gisce/erp/pulls/%s" % pr_number
    r = requests.get(url, headers=headers)
    pull = json.loads(r.text)
    commit = pull['head']['sha']
    url = "https://api.github.com/repos/gisce/erp/deployments?ref={}".format(commit)
    r = requests.get(url, headers=headers)
    res = json.loads(r.text)
    for deployment in res:
        print("Deployment id: {id} to {description}".format(**deployment))
        statusses = json.loads(requests.get(deployment['statuses_url'], headers=headers).text)
        for status in reversed(statusses):
            print("  - {state} by {creator[login]} on {created_at}".format(
                **status
            ))


@task
def mark_deploy_status(deploy_id, state='success', description=None):
    if not deploy_id:
        return
    logger.info('Marking as deployed %s on GitHub' % state)
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }

    url = "https://api.github.com/repos/gisce/erp/deployments/%s/statuses"
    payload = {'state': state}
    if description is not None:
        payload['description'] = description
    r = requests.post(url % deploy_id, data=json.dumps(payload),
                      headers=headers)
    logger.info('Deploy %s marked as %s' % (deploy_id, state))


@task
def export_patches_pr(pr_number):
    local("mkdir -p deploy/patches/%s" % pr_number)
    from_commit, to_commit, branch = find_from_to_commits(pr_number)
    if branch is None:
        export_patches_from_github(pr_number)
    else:
        export_patches_from_git(from_commit, to_commit, pr_number)


@task
def check_is_rolling():
    with settings(hide('everything'), sudo_user='erp', warn_only=True):
        with cd("/home/erp/src/erp"):
            res = sudo("git branch | grep '* rolling'")
            if res.return_code:
                abort("The repository is not in rolling mode")


@task
def apply_pr(pr_number, from_number=0, skip_upload=False):
    check_is_rolling()
    deploy_id = mark_to_deploy(pr_number)
    try:
        mark_deploy_status(deploy_id, 'pending')
        if not skip_upload:
            export_patches_from_github(pr_number)
            upload_patches(pr_number)
        apply_remote_patches(pr_number, from_number)
        mark_deploy_status(deploy_id, 'success')
    except Exception as e:
        logger.error(e)
        mark_deploy_status(deploy_id, 'error', description=e.message)

@task
def check_pr(pr_number):
    result = OrderedDict()
    repo = github_config(repository='gisce/erp')['repository']
    logger.info('Exporting patches from GitHub')
    headers = {'Authorization': 'token %s' % github_config()['token']}
    # Pagination documentation: https://developer.github.com/v3/#pagination
    base_url = 'https://api.github.com/repos/{0}/pulls/{1}/commits?per_page=100'
    url = base_url.format(repo, pr_number)
    r = requests.get(url, headers=headers)
    commits = json.loads(r.text)

    with settings(warn_only=True, sudo_user='erp'):
        with cd("/home/erp/src/erp"):
            for commit in commits:
                fh = StringIO.StringIO()
                commit_message = (
                    commit['commit']['message']
                ).replace('"', '\\"')
                git_command_template = 'git --no-pager log -F --grep="{0}" -n1'
                git_command = git_command_template.format(commit_message)
                with settings(output_prefix=False):
                    run(git_command, stdout=fh, shell=False)
                out = fh.getvalue()
                if len(out) > 0:
                    result[commit['commit']['message']] = True
                else:
                    result[commit['commit']['message']] = False
    for index, commit in enumerate(result, 1):
        num_commit = str(index).zfill(4)
        first_line = commit.splitlines()[0]
        if result[commit]:
            message = '{0} - {1} : \xE2\x9C\x85 Aplicat'
        else:
            message = '{0} - {1} : \xE2\x9D\x8C No aplicat'
        print(message.format(num_commit, first_line))

    return result
