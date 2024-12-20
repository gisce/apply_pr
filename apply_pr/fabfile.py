
# -*- coding: utf-8 -*-

from __future__ import (
    with_statement, absolute_import, unicode_literals, print_function
)
import json
import logging
import os
import io
import re
import pprint

import six
from fabric.api import local, run, cd, put, settings, abort, sudo, hide, task, env, prefix
from fabric.operations import open_shell, prompt
from fabric.contrib import files
from fabric.state import output
from fabric.exceptions import NetworkError
from fabric import colors
from osconf import config_from_environment
from slugify import slugify
from os.path import isdir
import requests
from io import BytesIO
from six import string_types, PY2
from tqdm import tqdm
if PY2:
    input = raw_input
else:
    pass

from collections import OrderedDict



from packaging import version as vsn
from giscemultitools.githubutils.objects import GHAPIRequester
from giscemultitools.githubutils.utils import GithubUtils

from requests.exceptions import ConnectionError
from .github_utils import github_config, is_github_token_valid
from .changelog import make_changelog

logger = logging.getLogger(__name__)


for k in output.keys():
    output[k] = False


def apply_pr_config(**config):
    return config_from_environment('APPLY_PR', **config)


config = apply_pr_config()

if config.get('logging'):
    logging.basicConfig(level=logging.INFO)

USE_SUDO = True
if config.get('no_sudo_mode'):
    from fabric.api import run as sudo
    USE_SUDO = False

DEPLOYED = {'pro': 'deployed', 'pre': 'deployed PRE', 'test': 'deployed PRE'}


def get_info_from_url(pr):
    if pr.startswith('https://'):
        vals = pr.split('/')
        info = {
           'owner': vals[3],
           'repository': vals[4],
           'pr': vals[6]
        }
        if len(vals) == 9 and vals[7] == 'commits':
            info['from_commit'] = vals[8]
        return info
    else:
        return {'pr': pr}


@task
def upload_diff(pr_number, src='/home/erp/src', repository='erp', sudo_user='erp'):
    temp_dir = '/tmp/%s.diff' % pr_number
    remote_dir = '{}/{}/patches/{}'.format(src, repository, pr_number)
    remote_dir_bkp = '{}/{}/patches/{}/backup'.format(src, repository, pr_number)
    sudo("mkdir -p %s" % remote_dir)
    sudo("mkdir -p %s" % remote_dir_bkp)
    sudo("chown -R {0}: {1}".format(sudo_user, remote_dir))
    with cd('{}/{}'.format(src, repository)):
        sudo("git diff > {}/pre_{}.diff".format(remote_dir_bkp, pr_number), user=sudo_user)
    diff_path = '{}/{}.diff'.format(remote_dir, pr_number)
    with io.open('deploy/patches/{}.diff'.format(pr_number), 'r', encoding='utf-8') as dfile:
        logger.info('Uploading diff {}.diff'.format(pr_number))
        put('deploy/patches/{}.diff'.format(pr_number), temp_dir, use_sudo=USE_SUDO)
    sudo("mv %s %s" % (temp_dir, diff_path))
    sudo("chown {0}: {1}".format(sudo_user, diff_path))


@task
def upload_patches(
    pr_number, from_commit=None, src='/home/erp/src', repository='erp', sudo_user='erp'
):
    temp_dir = '/tmp/%s' % pr_number
    remote_dir = '{}/{}/patches/{}'.format(
        src, repository, pr_number
    )
    sudo("mkdir -p %s" % remote_dir)
    sudo("mkdir -p %s" % temp_dir)
    patches = [p for p in local(
        'ls -1 deploy/patches/%s/' % pr_number, capture=True
    ).split('\n') if p]
    for patch in tqdm(patches, desc='  Uploading'):
        if not patch:
            continue
        if from_commit:
            with io.open('deploy/patches/%s/%s' % (pr_number, patch), 'r', encoding='utf8') as pfile:
                commit = pfile.readline().split(' ')[1]
                if commit != from_commit:
                    logger.info('Skipping patch {}'.format(patch))
                    continue
                else:
                    from_commit = None
        logger.info('Uploading patch {}'.format(patch))
        put('deploy/patches/%s/%s' % (pr_number, patch),
            temp_dir, use_sudo=USE_SUDO)
        remote_patch_file = '{}/{}'.format(temp_dir, patch)
        sudo("mv %s %s" % (remote_patch_file, remote_dir))
    sudo("chown -R {0}: {1}".format(sudo_user, remote_dir))


@task
def apply_remote_diff(pr_number, src='/home/erp/src', repository='erp',
                      sudo_user='erp', reject=False
):
    with settings(sudo_user=sudo_user):
        with cd("{}/{}".format(src, repository)):
            diff_file = 'patches/{pr_number}/{pr_number}.diff'.format(
                pr_number=pr_number)
            PatchApplier.apply(diff_file, reject=reject, sudo_user=sudo_user)


@task
def apply_remote_patches(
    name, from_patch=0, src='/home/erp/src', repository='erp', sudo_user='erp',
    auto_exit=True
):
    from_commit = None
    if isinstance(from_patch, string_types) and len(from_patch) == 40:
        from_commit = from_patch
        logger.info('Applying from commit {}'.format(from_commit))
        from_patch = 0
    else:
        from_patch = int(from_patch)
        logger.info('Applying from number {}'.format(from_patch))
    with settings(warn_only=True, sudo_user=sudo_user):
        with hide('output'):
            patches = sudo("ls -1 {}/{}/patches/{}/*.patch".format(
                src, repository, name
            ))
        patches_to_apply = []
        for patch in patches.split():
            if from_patch:
                number = int(os.path.basename(patch).split('-')[0])
                if number < from_patch:
                    logger.info('Skipping patch %s' % patch)
                    continue
            elif from_commit:
                commit = sudo('head -n1 {} | cut -d " " -f 2'.format(patch))
                if commit != from_commit:
                    logger.info('Skipping patch %s' % patch)
                    continue
                else:
                    from_commit = None
            patches_to_apply.append(patch)

        if patches_to_apply:
            with cd("{}/{}".format(src, repository)):
                git_am = GitApplier(patches_to_apply)
                if auto_exit:
                    git_am.auto_exit = True
                git_am.run()


class WiggleException(Exception):
    pass

class GitHubException(Exception):
    pass


class PatchApplier(object):

    @staticmethod
    def apply(diff, stash=True, reject=False, message=None, sudo_user='erp'):
        old_prefix = env.sudo_prefix
        env.sudo_prefix = "sudo -H -S -p '%(sudo_prompt)s' "
        need_stash = sudo(
            "test -f .gitignore && git ls-files -om -X .gitignore || git ls-files -om", user=sudo_user
        )
        stashed = False
        if stash and not need_stash:
            stash = False
        if message is None:
            message = 'Apply {}'.format(diff)
        if stash:
            print(colors.yellow('Stashing all before...'))
            sudo("git stash -u")
            stashed = True
        try:
            if reject:
                reject = '  --reject'
            else:
                reject = ''
            print(colors.green('Applying diff {}'.format(diff)))
            if reject:
                try:
                    sudo(
                        "git apply {}{}".format(diff, reject),
                     )
                except:
                    print(colors.yellow('Some rejects ...'))
                rej = sudo(
                    "git status | grep rej;echo yes", user=sudo_user
                    )
                if rej != 'yes':
                    prompt(
                        colors.red(
                            "Manual resolve. "
                            "If nothing to commit, empty staged"
                            " and unstaged changes. Press Enter to continue.")
                    )
            else:
                from apply_pr.exceptions import ApplyError
                with settings(abort_exception=ApplyError):
                    sudo(
                        "git apply {}{}".format(diff, reject),
                    )
            empty_files = sudo(
                'git ls-files --modified;git ls-files -o --exclude-standard; echo empty'
            )
            if empty_files != 'empty':
                print(colors.green('Commit!'))
                sudo(
                    'git add -A && git commit -m "{}"'.format(message),
                )
            else:
                print(colors.green('Nothing to commit! Continue'))

        except Exception as e:
            print(colors.red('\U000026D4 Error applying diff'))
            raise
        finally:
            if stash and stashed:
                print(colors.yellow('Unstashing...'))
                sudo("git stash pop")
            env.sudo_prefix = old_prefix


class GitApplier(object):
    def __init__(self, patches):
        self.patches = patches
        self.pbar = tqdm(total=len(patches), desc='   Applying')
        self.clean = 0
        self.forced = 0
        self.auto_exit = 0

    def run(self):
        result = sudo(
            "git am %s" % ' '.join(self.patches),
            combine_stderr=True
        )
        self.catch_result(result)

    def catch_result(self, result):
        result_failed = result.failed
        if six.PY3:
            result_text = bytes(result, 'utf-8').decode('utf-8')
        else:
            result_text = result.decode('utf-8')
        for line in result_text.split('\n'):
            if re.match('Applying: ', line):
                tqdm.write(colors.green(line))
                self.pbar.update()
        if result_failed:
            if "git config --global user.email" in result_text:
                logger.error(
                    "Need to configure git for this user\n"
                )
                raise GitHubException(result_text)
            try:
                raise WiggleException
            except WiggleException:
                if self.auto_exit:
                    sudo("git am --abort")
                    logger.error('Aborting deploy and go back')
                    raise GitHubException
                prompt("Manual resolve...")
            finally:
                if not self.auto_exit:
                    to_commit = sudo(
                        "git diff --cached --name-only --no-color", pty=False
                    )
                    if to_commit:
                        self.resolve()
                    else:
                        self.skip()

    def skip(self):
        self.catch_result(sudo("git am --skip"))

    def abort(self):
        self.catch_result(sudo("git am --abort"))

    def resolve(self):
        self.catch_result(sudo("git am --resolved"))


class PatchFile(object):
    def __init__(self, patch_file):
        self.patch_file = patch_file
        self.applied = False

    @property
    def files(self):
        files_in_patch = []
        command = " grep '^diff' {}".format(self.patch_file)
        for line in sudo(command).split('\n'):
            files_in_patch.append(
                os.path.relpath(line.split(' ')[2], 'a')
            )
        return files_in_patch

    @classmethod
    def from_patch_number(cls, result, patches_to_apply):
        failed_patch_number = re.findall(
            'Patch failed at ([0-9]{4}) ', result
        )
        if failed_patch_number:
            failed_patch_number = failed_patch_number[0]
            for patch in patches_to_apply:
                if patch.split('/')[-1].startswith(failed_patch_number):
                    return cls(patch)
        return None

    def apply(self, reject=False):
        sudo("git apply {} {}".format(
            reject and '--reject' or '', self.patch_file
        ))
        self.applied = True

    def wiggle(self):
        if not self.applied:
            self.apply(reject=True)
        for file_in_patch in self.files:
            rej_file = '{}.rej'.format(file_in_patch)
            porig_file = '{}.porig'.format(file_in_patch)
            if files.exists(rej_file):
                result = sudo("wiggle --replace {} {}".format(
                    file_in_patch, rej_file
                ))
                if result.failed:
                    raise WiggleException
                sudo("rm -f {} {}".format(rej_file, porig_file))
            removed = sudo("git status --porcelain {} | grep '^ D'".format(
                file_in_patch
            )).strip()
            if removed:
                sudo("git rm -f {}".format(file_in_patch))
            else:
                sudo("git add -f {}".format(file_in_patch))

    def add(self):
        for file_in_patch in self.files:
            sudo("git add {}".format(file_in_patch))


@task
def find_from_to_commits(pr_number, owner='gisce', repository='erp'):
    headers = {'Authorization': 'token %s' % github_config()['token']}
    url = "https://api.github.com/repos/{}/{}/pulls/{}".format(
        owner, repository, pr_number
    )
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
    deploy_path = "deploy/patches/{}".format(pr_number)
    try:
        if isdir(deploy_path):
            local("rm -r {}".format(deploy_path))
        local("mkdir -p {}".format(deploy_path))
    except BaseException as e:
        logger.error('Permission denied to write {} in the current directory'.format(deploy_path))
        raise
    local("git format-patch -o deploy/patches/%s %s..%s" % (
        pr_number, from_commit, to_commit)
    )


@task
def get_commits(pr_number, owner='gisce', repository='erp'):
    def is_merge_commit(commit):
        return bool(len(commit['parents']) > 1)

    # Pagination documentation: https://developer.github.com/v3/#pagination
    def parse_github_links_header(links_header):
        ret_links = {}
        full_links = links_header.split(',')
        for link in full_links:
            link_url, link_ref = link.split(';')
            link_url = link_url.strip()[1:-1]
            link_ref = link_ref.split('=')[-1].strip()[1:-1]
            ret_links[link_ref] = link_url
        return ret_links

    logger.info('Getting commits from GitHub')
    headers = {'Authorization': 'token %s' % github_config()['token']}
    repo = github_config(
        repository='{}/{}'.format(owner, repository))['repository']
    url = "https://api.github.com/repos/%s/pulls/%s/commits?per_page=100" \
          % (repo, pr_number)
    r = requests.get(url, headers=headers)
    commits = json.loads(r.text)
    if 'link' in r.headers:
        url_page = 1
        links = parse_github_links_header(r.headers['link'])
        while links['last'][-1] != str(url_page):
            url_page += 1
            tqdm.write(colors.yellow(
                '    - Getting extra commits page {}'.format(url_page)))
            r = requests.get(links['next'], headers=headers)
            commits += json.loads(r.text)

    for commit in commits:
        commit['commit']['is_merge_commit'] = is_merge_commit(commit)

    return commits


@task
def export_diff_from_github(pr_number, owner='gisce', repository='erp'):
    try:
        local("mkdir -p %s" % 'deploy/patches')
    except BaseException as e:
        logger.error('Permission denied to write deploy/patches in the current directory')
        raise
    diff_path = "deploy/patches/{}.diff".format(pr_number)
    tqdm.write('Exporting diff from Github')
    headers = {
        'Authorization': 'token %s' % github_config()['token'],
        'Accept': 'application/vnd.github.v3.diff'
    }
    url = 'https://api.github.com/repos/{owner}/{repository}/pulls/{pr_number}'.format(
        owner=owner, repository=repository, pr_number=pr_number
    )
    r = requests.get(url, headers=headers)
    with open(diff_path, 'wb') as f:
        f.write(r.text.encode('utf-8'))


@task
def export_patches_from_github(
    pr_number, from_commit=None, owner='gisce', repository='erp'
):
    patch_folder = "deploy/patches/%s" % pr_number
    try:
        local("mkdir -p %s" % patch_folder)
    except BaseException as e:
        logger.error('Permission denied to write {} in the current directory'.format(patch_folder))
        raise
    tqdm.write('Exporting patches from GitHub')
    headers = {'Authorization': 'token %s' % github_config()['token']}
    commits = get_commits(pr_number, owner=owner, repository=repository)
    patch_headers = headers.copy()
    patch_headers['Accept'] = 'application/vnd.github.patch'
    patch_number = 0
    tqdm.write("Exporting patches from PR:{}{}".format(
        pr_number, from_commit and '@{}'.format(from_commit) or ''
    ))
    for commit in tqdm(commits, desc='Downloading'):
        if commit['commit']['is_merge_commit']:
            logger.info('Skipping merge commit {sha}: {message}'.format(
                sha=commit['sha'], message=commit['commit']['message']
            ))
            continue
        if from_commit:
            if commit['sha'] != from_commit:
                logger.info('Skipping commit {sha}: {message}'.format(
                    sha=commit['sha'], message=commit['commit']['message']
                ))
                patch_number += 1
                continue
            else:
                from_commit = None
        patch_number += 1
        r = requests.get(commit['url'], headers=patch_headers)
        message = slugify(commit['commit']['message'][:64])
        filename = '%04i-%s.patch' % (patch_number, message)
        with open(os.path.join(patch_folder, filename), 'wb') as patch:
            logger.info('Exporting patch %s.' % filename)
            patch.write(r.text.encode('utf-8'))


@task
def mark_to_deploy(
    pr_number, hostname=False, owner='gisce', repository='erp'
):
    logger.info('Marking as deployed on GitHub')
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    url = "https://api.github.com/repos/{}/{}/pulls/{}".format(
        owner, repository, pr_number
    )
    r = requests.get(url, headers=headers)
    pull = json.loads(r.text)
    commit = pull['head']['sha']
    if not hostname:
        host = run("uname -n")
    else:
        host = hostname
    payload = {
        'ref': commit,
        'task': 'deploy',
        'auto_merge': False,
        'environment': host,
        'description': host,
        'required_contexts': [],
        'auto_inactive': False,
        'payload': {
            'host': host
        }
    }
    url = "https://api.github.com/repos/{}/{}/deployments".format(
        owner, repository
    )
    r = requests.post(url, data=json.dumps(payload), headers=headers)
    res = json.loads(r.text)
    if 'id' not in res:
        logger.info('Not marking deployment in github: %s' % res['message'])
        return 0
    deploy_id = res['id']
    logger.info('Deploy id: %s' % deploy_id)
    return deploy_id


def get_deploys(pr_number, owner='gisce', repository='erp', commit=None):
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    url = "https://api.github.com/repos/{}/{}/pulls/{}".format(
        owner, repository, pr_number
    )
    r = requests.get(url, headers=headers)
    pull = json.loads(r.text)
    if commit is None:
        commit = pull['head']['sha']
    url = "https://api.github.com/repos/{}/{}/deployments?sha={}".format(
        owner, repository, commit
    )
    r = requests.get(url, headers=headers)
    res = json.loads(r.text)
    res = sorted(res, key=lambda x: x['created_at'])
    deploys = []
    for deployment in res:
        statusses = json.loads(requests.get(deployment['statuses_url'], headers=headers).text)
        deployment['status'] = statusses
        deploys.append(deployment)
    return deploys


@task
def get_last_deploy(pr_number, hostname=False, owner='gisce', repository='erp'):
    if not hostname:
        hostname = run("uname -n")
    commits =  [x['sha'] for x in reversed(get_commits(pr_number, owner, repository))]
    logger.info('Finding last success deploy...')
    for idx, commit in tqdm(enumerate(commits), total=len(commits)):
        for deploy in get_deploys(pr_number, owner, repository, commit):
            if deploy['payload']['host'] == hostname:
                if deploy['status'][0]['state'] == 'success':
                    return deploy, commits[idx - 1]
    return None, None


@task
def print_deploys(pr_number, owner='gisce', repository='erp'):
    for deployment in get_deploys(pr_number, owner, repository):
        print("Deployment id: {id} to {description}".format(**deployment))
        for status in deployment['status']:
            status_text = (
                "  - {state} by {creator[login]} on {created_at}".format(
                    **status
                )
            )
            formatter = str
            if status['state'] == 'pending':
                formatter = colors.yellow
            elif status['state'] in ['error', 'failure']:
                formatter = colors.red
            elif status['state'] == 'success':
                formatter = colors.green
            print(formatter(status_text))


@task
def mark_deploy_status(
    deploy_id, state='success', description=None,
    owner='gisce', repository='erp', pr_number=None, environment='pro', no_set_label=False
):
    if not deploy_id:
        return
    logger.info('Marking as deployed %s on GitHub' % state)
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }

    url = "https://api.github.com/repos/{}/{}/deployments/{}/statuses".format(
        owner, repository, deploy_id
    )
    payload = {'state': state}
    if description is not None:
        payload['description'] = description
    r = requests.post(url, data=json.dumps(payload), headers=headers)
    logger.info('Deploy %s marked as %s' % (deploy_id, state))
    if state == 'success' and pr_number and environment is not None and not no_set_label:
        url = "https://api.github.com/repos/{}/{}/issues/{}/labels".format(
            owner, repository, pr_number
        )
        payload = {'labels': [DEPLOYED[environment]]}
        r = requests.post(url, data=json.dumps(payload), headers=headers)
        logger.info('Add Label to deploy on PR {}'.format(pr_number))


@task
def export_patches_pr(pr_number, owner='gisce', repository='erp'):
    try:
        local("mkdir -p deploy/patches/%s" % pr_number)
    except BaseException as e:
        logger.error('Permission denied to write deploy/patches/{} in the current directory'.format(pr_number))
        raise
    from_commit, to_commit, branch = find_from_to_commits(
        pr_number, owner=owner, repository=repository
    )
    if branch is None:
        export_patches_from_github(
            pr_number, owner=owner, repository=repository
        )
    else:
        export_patches_from_git(
            from_commit, to_commit, pr_number,
            owner=owner, repository=repository
        )


@task
def check_it_exists(src='/home/erp/src', repository='erp', sudo_user='erp'):
    with settings(hide('everything'), sudo_user=sudo_user, warn_only=True):
        res = sudo("ls {}/{}".format(src, repository))
        if res.return_code:
            message = "The repository {} does not exist or cannot be found in {}".format(repository, src)
            tqdm.write(colors.red(message))
            abort(message)


@task
def check_is_rolling(src='/home/erp/src', repository='erp', sudo_user='erp'):
    with settings(hide('everything'), sudo_user=sudo_user, warn_only=True):
        with cd("{}/{}".format(src, repository)):
            res = sudo("git branch | grep '* rolling'")
            if res.return_code:
                message = "The repository is not in rolling mode"
                tqdm.write(colors.red(message))
                abort(message)


@task
def check_am_session(src='/home/erp/src', repository='erp', sudo_user='erp'):
    with settings(hide('everything'), sudo_user=sudo_user, warn_only=True):
        with cd("{}/{}".format(src, repository)):
            res = sudo("ls .git/rebase-apply")
            if not res.return_code:
                message = "The repository is in the middle of an am session!"
                tqdm.write(colors.red(message))
                abort(message)


@task
def apply_pr(
        pr_number, from_number=0, from_commit=None, skip_upload=False,
        hostname=False, src='/home/erp/src', owner='gisce', repository='erp',
        sudo_user='erp', auto_exit=False, force_name=None, re_deploy=False,
        as_diff=False, environment='pro', reject=False, skip_rolling_check=False, no_set_label=False
):
    if force_name:
        repository_name = force_name
    else:
        repository_name = repository
    try:
        check_it_exists(src=src, repository=repository_name, sudo_user=sudo_user)
        if not skip_rolling_check:
            check_is_rolling(src=src, repository=repository_name, sudo_user=sudo_user)
        check_am_session(src=src, repository=repository_name, sudo_user=sudo_user)
    except NetworkError as e:
        logger.error('Error connecting to specified host')
        logger.error(e)
        raise
    if re_deploy:
        tqdm.write(colors.blue('\U0001F50E Trying to find last success deploymnet...'))
        last_deploy, from_commit = get_last_deploy(pr_number, hostname, owner, repository)
        if last_deploy:
            tqdm.write(colors.blue('\U00002705 Got it! is {sha}.'.format(**last_deploy)))
            if last_deploy['sha'] == from_commit:
                tqdm.write(colors.red('\U000026D4 No commits to deploy...'))
                exit(-1)
        else:
            tqdm.write(colors.blue('\U0001F62F Not found...'))
        resp = input('Deploy from {}? (y/n): '.format(from_commit or '0'))
        if resp.upper() != 'Y':
            exit(-1)
    deploy_id = mark_to_deploy(pr_number,
                               hostname=hostname,
                               owner=owner,
                               repository=repository)
    if not deploy_id:
        tqdm.write(colors.magenta(
            'No deploy id! you must mark the Pull Request manually'
        ))
    try:
        mark_deploy_status(deploy_id,
                           state='pending',
                           owner=owner,
                           repository=repository,
                           environment=environment,
                           no_set_label=no_set_label
                           )
        tqdm.write(colors.yellow("Marking to deploy ({}) \U0001F680".format(
            deploy_id
        )))
        if not skip_upload:
            if as_diff:
                export_diff_from_github(
                    pr_number, owner=owner, repository=repository
                )
                upload_diff(
                    pr_number, src=src, repository=repository,
                    sudo_user=sudo_user
                )
            else:
                export_patches_from_github(pr_number,
                                           from_commit,
                                           owner=owner,
                                           repository=repository)
                upload_patches(pr_number,
                               from_commit,
                               src=src,
                               repository=repository_name,
                               sudo_user=sudo_user)
        if as_diff:
            tqdm.write(colors.yellow("Applying diff \U0001F648"))
            check_am_session(src=src, repository=repository_name)
            result = apply_remote_diff(
                pr_number, src=src, repository=repository, sudo_user=sudo_user,
                reject=reject
            )
        else:
            if from_commit:
                from_ = from_commit
            else:
                from_ = from_number
            tqdm.write(colors.yellow("Applying patches \U0001F648"))
            check_am_session(src=src, repository=repository_name)
            result = apply_remote_patches(
                pr_number,
                from_,
                src=src,
                repository=repository_name,
                sudo_user=sudo_user,
                auto_exit=auto_exit,
            )
        mark_deploy_status(deploy_id,
                           state='success',
                           owner=owner,
                           repository=repository,
                           pr_number=pr_number,
                           no_set_label=no_set_label,
                           environment=environment
                           )
        tqdm.write(colors.green("Deploy success \U0001F680"))
        return True
    except Exception as e:
        logger.error(e)
        mark_deploy_status(deploy_id,
                           state='error',
                           description='{}'.format(e),
                           owner=owner,
                           repository=repository,
                           no_set_label=no_set_label
                           )
        tqdm.write(colors.red("Deploy failure \U0001F680"))
        return False


@task
def mark_deployed(pr_number, hostname=False, owner='gisce', repository='erp', environment='pre'):
    deploy_id = mark_to_deploy(pr_number,
                               hostname=hostname,
                               owner=owner,
                               repository=repository)
    mark_deploy_status(deploy_id,
                       state='success',
                       owner=owner,
                       repository=repository,
                       pr_number=pr_number,
                       environment=environment)

@task
def check_pr(pr_number, src='/home/erp/src', owner='gisce', repository='erp', sudo_user='erp'):
    result = OrderedDict()
    logger.info('Getting patches from GitHub')
    commits = get_commits(
        pr_number=pr_number, owner=owner, repository=repository)

    with settings(warn_only=True, sudo_user=sudo_user):
        with cd("{}/{}".format(src, repository)):
            for commit in commits:
                fh = BytesIO()
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

@task
def prs_status(
        prs, separator=' ', owner='gisce', repository='erp', version=False):
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    prs = re.sub('{}+'.format(separator), separator, prs)
    pr_list = prs.split(separator)
    PRS = {}
    ERRORS = []
    TO_APPLY = []
    TO_APPLY_CAUSE_PROJECT_VERSION_ERROR = []
    CLOSED_PRS = []
    IN_PROJECTS = []
    rep = GHAPIRequester(owner, repository)
    def get_prs_info(plist):
        res = []
        for _pr in tqdm(list(set(plist)), desc='Getting pr data from Github'):
            try:
                res.append(
                    GithubUtils.plain_get_commits_sha_from_merge_commit(
                        rep.get_pull_request_projects_and_commits(int(_pr))
                    )
                )
            except Exception:
                res.append({'pullRequest': {'number': _pr}})
        if res:
            max_meged_at = '2999-12-27T06:22:04Z'
            return sorted(
                res, key=lambda _p: (
                    _p['pullRequest'].get('mergedAt', max_meged_at) or max_meged_at,
                    _p['pullRequest'].get('createdAt') if (_p['pullRequest'].get('mergedAt', max_meged_at) or max_meged_at) == max_meged_at else ''
                )
            )
        return res

    def check_version_project_done(project_items):
        if version:
            parsed_version = version.split('.')
            parsed_version = '{}.{}'.format(parsed_version[0], parsed_version[1])
            for _project in project_items:
                if _project['project_name'].startswith(parsed_version) and _project['card_state'] != 'Done':
                    return False
        return True

    for pull_info in tqdm(get_prs_info(pr_list), desc='Process PRs info'):
        pr_number = pull_info['pullRequest']['number']
        try:
            pull = pull_info['pullRequest']
            projects_info = pull_info.get('projectItems', None)
            projects_show = ''
            to_apply = '{}'.format(str(pr_number))
            projects = ''
            if projects_info:
                projects = ','.join(
                    [x['project_name'] for x in projects_info if x['card_state'] == 'Done']
                )
                if projects:
                    projects_show = 'PROJECTS => {}'.format(projects)
                    to_apply += ' ({})'.format(projects)
            state_pr = pull['state']
            merged_at = pull['mergedAt']
            created_at = pull['createdAt']
            milestone = pull['milestone'] or '(With out Milestone)'
            message = (
                'PR {number}=>'
                ' state {state_pr}'
                ' merged_at {merged_at}'
                ' created_at {created_at}'
                ' milestone {milestone}'
                ' {projects} '.format(
                    number=pr_number, state_pr=state_pr,
                    merged_at=merged_at, created_at=created_at,
                    milestone=milestone, projects=projects_show
                )
            )
            if version:
                if milestone != '(With out Milestone)' and vsn.parse(milestone) <= vsn.parse(version):
                    if state_pr.upper() != 'MERGED':
                        message = colors.yellow(message)
                        if state_pr.upper() == 'CLOSED':
                            CLOSED_PRS.append(to_apply)
                        elif not projects:
                            TO_APPLY.append(to_apply)
                        else:
                            IN_PROJECTS.append(to_apply)
                    else:
                        message = colors.green(message)
                else:
                    message = colors.red(message)
                    if not projects:
                        TO_APPLY.append(to_apply)
                    elif not check_version_project_done(projects_info):
                        TO_APPLY.append('{}'.format(str(pr_number)))
                        TO_APPLY_CAUSE_PROJECT_VERSION_ERROR.append(to_apply)
                    else:
                        IN_PROJECTS.append(to_apply)
            PRS.setdefault(milestone, [])
            PRS[milestone] += [message]
        except Exception as e:
            # logger.error('Error PR {0}'.format(pr_number))
            err_msg = colors.red(
                'Error PR {2} : https://github.com/{0}/{1}/pull/{2}'.format(
                    owner, repository, pr_number
                )
            )
            tqdm.write(err_msg)
            ERRORS.append(err_msg)
    for milestone in sorted(PRS.keys()):
        print('\nMilestone {}'.format(milestone))
        for prmsg in PRS[milestone]:
            print('\t{}'.format(prmsg))
    for prmsg in ERRORS:
        print('ERR\t{}'.format(prmsg))
    if version:
        print(colors.magenta('\nIncluded in projects\n'))
        for x in IN_PROJECTS:
            print(colors.magenta('* {}'.format(x)))
        print(colors.red('\nIncluded in version project but in Error State\n'))
        for _pr_project in TO_APPLY_CAUSE_PROJECT_VERSION_ERROR:
            print(colors.red('* {}'.format(_pr_project)))
        if CLOSED_PRS:
            print(colors.red('\n############# Closed PRS: "{}"\n'.format(
                ' '.join(CLOSED_PRS)
            )))
        if ERRORS:
            print(colors.yellow('\n⚠ ️WARNING ⚠ ️! ERRORS IN PRS. MUST BE REVIEW\n'))
            print(colors.yellow('##########################################\n'))
            for prmsg in ERRORS:
                print('ERR\t{}'.format(prmsg))
            print(colors.yellow('############# END ERROR PRS ###############\n'))
        print(colors.yellow(
            '\nNot Included: "{}"\n'.format(' '.join(TO_APPLY))
        ))
        for x in TO_APPLY:
            print(
                 'curl -H \'Authorization: token {token}\' '
                 '-H "Accept: application/vnd.github.v3.diff" '
                 'https://api.github.com/repos/gisce/erp/pulls/{pr} --output {pr}.diff'.format(
                       pr=x, token="$GITHUB_TOKEN")
            )
    return True

@task
def auto_changelog(milestone, show_issues=True):

    def get_label(label_keys, labels):
        for label in labels:
            name = label['name'].lower()
            for key in label_keys:
                if key in name:
                    return key
        return 'others'

    def print_item(item):
        message = u'* {title} [#{number}]({url})'.format(
            title=item['title'], number=item['number'], url=item['url']
            )
        return (message)

    logger.info('Marking as deployed on GitHub')
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    url = "https://api.github.com/search/issues?q=is:merged+milestone:"+milestone+"&type=pr&sort=created&order=asc&per_page=250"
    r = requests.get(url, headers=headers)
    pull = json.loads(r.text)
    isses_desc = []
    pulls_desc = {'others': [],
                  'facturacio': [],
                  'atr': [],
                  'telegestio': [],
                  'gis': [],
                  'core': [],
                  'bug': [],
                  }

    label_keys = pulls_desc.keys()
    other_desc = []
    for item in pull['items']:
        url_item = item['html_url']
        item_info = {'title': item['title'], 'number': item['number'], 'url': url_item}
        if 'issues' in url_item:
            isses_desc.append(item_info)
        elif 'pull' in url_item:
            key = get_label(label_keys, item['labels'])
            pulls_desc[key].append(item_info)
        else:
            other_desc.append(item_info)
    print ("# Change log version {milestone}\n".format(milestone=milestone))
    for key in label_keys:
        print ('\n## {key}\n'.format(key=key.upper()))
        for pull in pulls_desc[key]:
            print(print_item(pull, milestone))
    if show_issues:
        print('\n# Issues:  \n')
        for issue in isses_desc:
            print(print_item(issue, milestone))
    if other_desc:
        print('\n# Others :  \n')
        for pull in other_desc:
            print(print_item(pull, milestone))
    return True

@task
def create_changelog(
        milestone, show_issues=False, changelog_path='/tmp',
        owner='gisce', repository='erp'):
    make_changelog(milestone, show_issues=show_issues,
                   changelog_path=changelog_path,
                   owner=owner, repository=repository)