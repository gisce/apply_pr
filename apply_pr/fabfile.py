from __future__ import (
    with_statement, absolute_import, unicode_literals, print_function
)
import json
import logging
import os
import io
import re
import pprint

from fabric.api import local, run, cd, put, settings, abort, sudo, hide, task
from fabric.operations import open_shell, prompt
from fabric.contrib import files
from fabric.state import output
from fabric import colors
from osconf import config_from_environment
from slugify import slugify
import requests
import StringIO
from collections import OrderedDict

from tqdm import tqdm


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


@task
def upload_patches(pr_number, from_commit=None):
    temp_dir = '/tmp/%s' % pr_number
    remote_dir = '/home/erp/src/erp/patches/{}'.format(pr_number)
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
    sudo("chown -R erp: %s" % remote_dir)


@task
def apply_remote_patches(name, from_patch=0):
    from_commit = None
    if isinstance(from_patch, basestring) and len(from_patch) == 40:
        from_commit = from_patch
        logger.info('Applying from commit {}'.format(from_commit))
        from_patch = 0
    else:
        from_patch = int(from_patch)
        logger.info('Applying from number {}'.format(from_patch))
    with settings(warn_only=True, sudo_user='erp'):
        with hide('output'):
            patches = sudo("ls -1 /home/erp/src/erp/patches/%s/*.patch" % name)

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
            with cd("/home/erp/src/erp"):
                git_am = GitApplier(patches_to_apply)
                git_am.run()


class WiggleException(Exception):
    pass


class GitApplier(object):
    def __init__(self, patches):
        self.patches = patches
        self.pbar = tqdm(total=len(patches), desc='   Applying')
        self.clean = 0
        self.forced = 0

    def run(self):
        result = sudo("git am %s" % ' '.join(self.patches), combine_stderr=True)
        self.catch_result(result)

    def catch_result(self, result):
        for line in result.split('\n'):
            if re.match('Applying: ', line):
                tqdm.write(colors.green(line))
                self.pbar.update()
                import time
                time.sleep(0.1)
        if result.failed:
            patch = PatchFile.from_patch_number(result, self.patches)
            if patch:
                tqdm.write(colors.red("Wiggled! \U0001F635"))
                try:
                    patch.wiggle()
                except WiggleException:
                    prompt("Manual resolve...")
                finally:
                    to_commit = sudo(
                        "git diff --cached --name-only --no-color", pty=False
                    )
                    if to_commit:
                        self.resolve()
                    else:
                        self.skip()
            else:
                self.abort()

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
def export_patches_from_github(pr_number, from_commit=None):
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
def apply_pr(pr_number, from_number=0, from_commit=None, skip_upload=False):
    check_is_rolling()
    deploy_id = mark_to_deploy(pr_number)
    if not deploy_id:
        tqdm.write(colors.magenta(
            'No deploy id! you must mark the pr manually'
        ))
    try:
        mark_deploy_status(deploy_id, 'pending')
        tqdm.write(colors.yellow("Marking to deploy ({}) \U0001F680".format(
            deploy_id
        )))
        if not skip_upload:
            pass
            export_patches_from_github(pr_number, from_commit)
            upload_patches(pr_number, from_commit)
        if from_commit:
            from_ = from_commit
        else:
            from_ = from_number
        tqdm.write(colors.yellow("Applying patches \U0001F648"))
        apply_remote_patches(pr_number, from_)
        mark_deploy_status(deploy_id, 'success')
        tqdm.write(colors.green("Deploy success \U0001F680"))
    except Exception as e:
        logger.error(e)
        mark_deploy_status(deploy_id, 'error', description=e.message)
        tqdm.write(colors.red("Deploy failure \U0001F680"))


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

@task
def prs_status(prs, separator=' '):
    logger.info('Marking as deployed on GitHub')
    headers = {
        'Accept': 'application/vnd.github.cannonball-preview+json',
        'Authorization': 'token %s' % github_config()['token']
    }
    prs = re.sub('{}+'.format(separator), separator, prs)
    pr_list = prs.split(separator)
    PRS = {}
    for pr_number in pr_list:
        try:
            url = "https://api.github.com/repos/gisce/erp/pulls/%s" % pr_number
            r = requests.get(url, headers=headers)
            pull = json.loads(r.text)
            state_pr = pull['state']
            merged_at = pull['merged_at']
            milestone = pull['milestone']['title']
            message = 'PR {number}=> state {state_pr} merged_at {merged_at} milestone {milestone}'.format(
                number=pr_number, state_pr=state_pr, merged_at=merged_at, milestone=milestone
            )
            PRS.setdefault(milestone, [])
            PRS[milestone] += [message]
        except Exception as e:
            logger.error('Error PR {0}'.format(pr_number))
            print('Error PR {0}'.format(pr_number))
    pprint.pprint(PRS)
    return True
