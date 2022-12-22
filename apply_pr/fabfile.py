
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
import StringIO
from collections import OrderedDict

from tqdm import tqdm
from packaging import version as vsn


logger = logging.getLogger(__name__)


for k in output.keys():
    output[k] = False


def github_config(**config):
    return config_from_environment('GITHUB', ['token'], **config)


def apply_pr_config(**config):
    return config_from_environment('APPLY_PR', **config)


config = apply_pr_config()
if config.get('logging'):
    logging.basicConfig(level=logging.INFO)

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
        put('deploy/patches/{}.diff'.format(pr_number), temp_dir, use_sudo=True)
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
            temp_dir, use_sudo=True)
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
            PatchApplier.apply(diff_file, reject=reject)


@task
def apply_remote_patches(
    name, from_patch=0, src='/home/erp/src', repository='erp', sudo_user='erp',
    auto_exit=True
):
    from_commit = None
    if isinstance(from_patch, basestring) and len(from_patch) == 40:
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
    def apply(diff, stash=True, reject=False, message=None):
        need_stash = sudo("test -f .gitignore && git ls-files -om -X .gitignore || git ls-files -om")
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
            old_prefix = env.sudo_prefix
            env.sudo_prefix = "sudo -H -S -p '%(sudo_prompt)s' "
            if reject:
                try:
                    sudo(
                        "git apply {}{}".format(diff, reject),
                     )
                except:
                    print(colors.yellow('Some rejects ...'))
                rej = sudo(
                    "git status | grep rej;echo yes", user='erp'
                    )
                if rej != 'yes':
                    prompt(
                        colors.red(
                            "Manual resolve. "
                            "If nothing to commit, empty staged"
                            " and unstaged changes. Press Enter to continue.")
                    )
            else:
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
            env.sudo_prefix = old_prefix
        except Exception as e:
            print(colors.red('\U000026D4 Error applying diff'))
            raise
        finally:
            if stash and stashed:
                print(colors.yellow('Unstashing...'))
                sudo("git stash pop")


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
        for line in result.decode('utf-8').split('\n'):
            if re.match('Applying: ', line):
                tqdm.write(colors.green(line))
                self.pbar.update()
        if result.failed:
            if "git config --global user.email" in result.decode('utf-8'):
                logger.error(
                    "Need to configure git for this user\n"
                )
                raise GitHubException(result)
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
    return commits


@task
def export_diff_from_github(pr_number, owner='gisce', repository='erp'):
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
    with open(diff_path, 'w') as f:
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
        if commit['commit']['message'].lower().startswith('merge'):
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
        with open(os.path.join(patch_folder, filename), 'w') as patch:
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
        logger.error('Permission denied to write deploy/patches/{} in the current directory'.format(patch_folder))
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
            message = "The repository does not exist or cannot be found"
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
        resp = raw_input('Deploy from {}? (y/n): '.format(from_commit or '0'))
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
            apply_remote_diff(
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
                           no_set_label=no_set_label
                           )
        tqdm.write(colors.green("Deploy success \U0001F680"))
        return True
    except Exception as e:
        logger.error(e)
        mark_deploy_status(deploy_id,
                           state='error',
                           description=e.message,
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
    for pr_number in tqdm(pr_list, desc='Getting pr data from Github'):
        try:
            url = "https://api.github.com/repos/{}/{}/pulls/{}".format(
                owner, repository, pr_number
            )
            r = requests.get(url, headers=headers)
            pull = json.loads(r.text)
            state_pr = pull['state']
            merged_at = pull['merged_at']
            milestone = pull['milestone']['title']
            message = (
                'PR {number}=>'
                ' state {state_pr}'
                ' merged_at {merged_at}'
                ' milestone {milestone}'.format(
                    number=pr_number, state_pr=state_pr,
                    merged_at=merged_at, milestone=milestone
                )
            )
            if version:
                if vsn.parse(milestone) <= vsn.parse(version):
                    if state_pr != 'closed':
                        message = colors.yellow(message)
                        TO_APPLY.append(str(pr_number))
                    else:
                        message = colors.green(message)
                else:
                    message = colors.red(message)
                    TO_APPLY.append(str(pr_number))
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
        TO_APPLY = sorted(list(set(TO_APPLY)))
        print(colors.yellow(
            '\nNot Included: "{}"\n'.format(' '.join(TO_APPLY))
        ))
        for x in TO_APPLY:
            print(
                 'curl -H \'Authorization: token {token}\' '
                 '-H "Accept: application/vnd.github.v3.diff" '
                 'https://api.github.com/repos/gisce/erp/pulls/{pr} --output {pr}.diff'.format(
                       pr=x, token=github_config()['token'])
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
            print(print_item(pull))
    if show_issues:
        print('\n# Issues:  \n')
        for issue in isses_desc:
            print(print_item(issue))
    if other_desc:
        print('\n# Others :  \n')
        for pull in other_desc:
            print(print_item(pull))
    return True


@task
def create_changelog(
        milestone, show_issues=False, changelog_path='/tmp',
        owner='gisce', repository='erp'):
    import copy

    SKIP_LABELS = ['custom', 'to be merged','deployed', 'traduccions']
    GAS_LABEL = 'gas'
    ELEC_LABEL = u'eléctrico'
    OFICINA_VIRTUAL = 'oficinavirtual'
    TYPE_LABELS = [ELEC_LABEL, GAS_LABEL, OFICINA_VIRTUAL]
    TOP_FEATURE = u':fire: top feature'
    COMMON_KEY = u'COMÚN'
    def get_label(label_keys, labels, skip_custom=False):
        if not skip_custom:
            for label in labels:
                name = label['name'].lower()
                if name == 'custom':
                    return 'custom'
        for label in labels:
            name = label['name'].lower()
            for key in label_keys:
                if key in name:
                    return key
        return 'others'

    def print_item(item):
        title_anchor = slugify(item['title'])
        message = u'\n* {title} [:fa-plus-circle: detalles](detailed_{milestone}#{title_anchor}-{number}) - [:fa-github: {number}]({url})'.format(
            title=item['title'], number=item['number'], url=item['url'],
            milestone=milestone, title_anchor=title_anchor
            )
        return (message)

    def print_item_detail(item, key=None):
        body = item['body'] or ''
        body = re.sub('^# ', '#### ', body).strip()
        body = re.sub('\n# ', '\n#### ', body).strip()
        body = re.sub('^## ', '#### ', body).strip()
        body = re.sub('\n## ', '\n#### ', body).strip()
        body = re.sub(
            '#(\d+)',
            '[:fa-github: \g<1>](https://github.com/{}/{}/pull/\g<1>)'.format(
                owner, repository
            ), body)
        body = re.sub(
            '- #(\d+)',
            '- [:fa-github:  \g<1>](https://github.com/{}/{}/pull/\g<1>)'
            ''.format(
                owner, repository
            ), body)
        label = ''
        if key:
            for l in item['labels']:
                if l['name'] not in SKIP_LABELS:
                    label += u' <span class="label" ' \
                             u'style="background-color: #{color};">{name}</span>'.format(
                                    name=l['name'],
                        color=l['color'])
                label = '\n'+label
        message = (
            u'\n\n### {title} [:fa-github: {number}]({url})  {label}\n\n{body}\n ---'.format(
                title=item['title'], number=item['number'],
                url=item['url'], body=body, label=label
            )
        )
        return message

    logger.info('Getting PRs from GitHub')
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    url = ("https://api.github.com/search/issues"
           "?q=is:pr+is:merged+milestone:{milestone}+repo:{owner}/{repository}"
           "&type=pr"
           "&sort=create"
           "d&order=asc"
           "&per_page=250").format(
        milestone=milestone, owner=owner, repository=repository
    )
    r = requests.get(url, headers=headers)

    pull = json.loads(r.text)
    total_prs = pull['total_count']
    pulls_items= []
    total_fetch = 0
    page = 1
    while total_fetch < total_prs:
        items = pull['items']
        # pprint.pprint(items)
        total_fetch += len(items)
        pulls_items += items
        if total_fetch >= total_prs:
            break
        page += 1
        new_url = url + "&page={}".format(page)
        r = requests.get(new_url, headers=headers)
        pull = json.loads(r.text)
        if page == 10:
            break

    isses_desc = []
    top_pulls = []
    pulls_desc = OrderedDict(
        [
            ('custom', []),
            ('bug', []),
            ('core', []),
            ('atr', []),
            ('telegestio', []),
            ('gis', []),
            ('facturacio', []),
            ('medidas', []),
            ('others', []),
            ('traduccions', []),

        ]
    )
    pulls_sep = {
        GAS_LABEL: copy.deepcopy(pulls_desc),
        ELEC_LABEL: copy.deepcopy(pulls_desc),
        OFICINA_VIRTUAL: copy.deepcopy(pulls_desc),
        'others': copy.deepcopy(pulls_desc)
    }
    label_keys = pulls_desc.keys()
    other_desc = []
    changelog_file = 'changelog_{}.md'.format(milestone)
    top_file = 'top_{}.md'.format(milestone)
    detailed_file = 'detailed_{}.md'.format(milestone)
    print('Total PRs: {}'.format(total_prs))
    number = 0
    for item in tqdm(pulls_items):
        url_item = item['html_url']
        item_info = {
            'title': item['title'],
            'number': item['number'],
            'url': url_item,
            'body': item['body'],
            'labels': item['labels'],
        }
        if 'issues' in url_item:
            isses_desc.append(item_info)
        elif 'pull' in url_item:
            p_url = "https://api.github.com/repos/{owner}/{repository}/pulls/{number}".format(
                owner=owner, repository=repository, number=item_info['number']
            )
            try:
                r = requests.get(p_url, headers=headers)
                pull_desc = json.loads(r.text)
                item_info['pull_info'] = pull_desc
                branch = pull_desc['base']['ref']
            except ConnectionError as e:
                tqdm.write('Failed to get infor for  {}'.format(item_info['number']))
                branch = 'developer'
            
            if branch != 'developer':
                continue
            type_key = get_label(TYPE_LABELS, item['labels'], skip_custom=True)
            top = get_label([TOP_FEATURE], item['labels'], skip_custom=True)
            if TOP_FEATURE.lower() in top:
                top_pulls.append(item_info)
            key = get_label(label_keys, item['labels'])
            pulls_sep[type_key][key].append(item_info)
        else:
            other_desc.append(item_info)
        number += 1
    logger.info('Total imported: {}'.format(number))
    pulls_sep[GAS_LABEL].pop('custom')
    pulls_sep[ELEC_LABEL].pop('custom')
    pulls_sep[ELEC_LABEL].pop('traduccions')
    pulls_sep[GAS_LABEL].pop('traduccions')
    for key in ['gis', 'telegestio', 'medidas', 'facturacio']:
        pulls_sep[ELEC_LABEL][key] += pulls_sep['others'][key]
        pulls_sep['others'][key] = []
    pulls_sep['others'].pop('custom')
    pulls_sep['others'].pop('traduccions')
    pulls_sep[COMMON_KEY] = pulls_sep.pop('others')
    index_bug = label_keys.index('bug')
    label_keys.pop(index_bug)
    label_keys.append('bug')

    # TOP FEATURES
    logger.info('Writting top feature on {}/:'.format(changelog_path))
    with open('{}/{}'.format(changelog_path, top_file), 'w') as f:
        f.write("# TOP FEATURES version {milestone}\n".format(milestone=milestone))
        for pull in top_pulls:
            f.write(print_item(pull))


    # CHANGELOGS
    logger.info('Writting changelog on {}/:'.format(changelog_path))
    with open('{}/{}'.format(changelog_path, changelog_file), 'w') as f:
        f.write("# Changelog version {milestone}\n".format(milestone=milestone))
        for type_l in TYPE_LABELS + [COMMON_KEY]:
            f.write('\n## {key}\n'.format(key=type_l.upper()))
            for key in label_keys:
                pulls = pulls_sep[type_l].get(key,[])
                if pulls:
                    f.write('\n### {key}\n'.format(key=key.upper()))
                    for pull in pulls:
                        f.write(print_item(pull))
        if show_issues:
            f.write('\n# Issues:  \n')
            for issue in isses_desc:
                f.write(print_item(issue))
        if other_desc:
            f.write('\n# Others :  \n')
            for pull in other_desc:
                f.write(print_item(pull))
    logger.info('    {}/{}'.format(changelog_path, changelog_file))
    with open('{}/{}'.format(changelog_path, detailed_file) , 'w') as f:
        f.write("# Detalles version {milestone}\n".format(milestone=milestone))
        for type_l in TYPE_LABELS + [COMMON_KEY]:
            f.write('\n## {key}\n'.format(key=type_l.upper()))
            for key in label_keys:
                pulls = pulls_sep[type_l].get(key,[])
                if pulls:
                    f.write('\n### {key}\n'.format(key=key.upper()))
                    for pull in pulls:
                        f.write(print_item_detail(pull, key))
        if show_issues:
            logger.info('\n# Issues:  \n')
            for issue in isses_desc:
                f.write(print_item_detail(issue, key))
        if other_desc:
            print('\n# Others :  \n')
            for pull in other_desc:
                f.write(print_item_detail(pull, key))
    logger.info('    {}/{}'.format(changelog_path, detailed_file))
    return True
