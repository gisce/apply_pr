from __future__ import with_statement
import logging
import os

from fabric.api import local, run, cd, put, settings, abort, env
import semver
from hipfab import hipfab


log_level = getattr(logging, os.environ.get('LOG_LEVEL', 'INFO').upper())
logging.basicConfig(level=log_level)
logger = logging.getLogger(__name__)


hipfab.DEBUG = False
hipfab.get_token = lambda: "d292525f03591a4243d8d55f860b65"

env.hosts = ['erp61-elec@demo-crm-aguas.gisce.net']


def last_version(where='local'):
    cmd = "git describe --abbrev=0 --tags"
    if where == 'local':
        version = local(cmd, capture=True)
    else:
        with settings(warn_only=True):
            with cd('~/src/erp'):
                version = run(cmd)
                if version.failed:
                    version = 'v0.0.0'
    logger.debug('Last version is %s' % version)
    return version


def has_changes(version=None):
    if not version:
        version = last_version()
    changes = local("git log --oneline  --abbrev=0 %s..HEAD" % version,
                    capture=True)
    return bool(changes)


def upload_version(version, **kwargs):
    version = version.lstrip('v')
    parsed = semver.parse(version)
    for k in ('prerelease', 'build'):
        if k in kwargs:
            parsed[k] = kwargs[k]
    for k in ('major', 'minor', 'patch'):
        if kwargs.get(k):
            parsed[k] += 1
    version = 'v%(major)s.%(minor)s.%(patch)s' % parsed
    if parsed.get('prerelease'):
        version += '-%(prerelease)s' % parsed
    if parsed.get('build'):
        version += '+%(build)s' % parsed
    local("git tag %s" % version)
    logger.info("New version set to %s" % version)
    return version


def set_remote_version(version):
    with cd('~/src/erp'):
        run("git tag %s" % version)
        logger.info('Remote version set to %s' % version)


def export_patches(from_version, to_version):
    logger.info('Exporting patches from %s to %s' % (from_version, to_version))
    local("mkdir -p deploy/patches/%s" % to_version)
    local("git format-patch -o deploy/patches/%s %s..%s" % (
        to_version, from_version, to_version)
    )


def upload_patches(version):
    remote_dir = '~/src/erp/deploy/patches/%s' % version
    run("mkdir -p %s" % remote_dir)
    put('deploy/patches/%s/*.patch' % version, remote_dir)


def apply_remote_patches(version):
    with settings(warn_only=True):
        with cd('~/src/erp'):
            result = run("git am deploy/patches/%s/*.patch" % version)
        if result.failed:
            logger.error('Applying patches for version %s failed' % version)
            with cd('~/src/erp'):
                run("git am --abort")
            abort('Aborting')


def update_all():
    logger.info("Updating erp version")
    with cd('~/src/erp/server'):
        run("PYTHONPATH=../sitecustomize/ ./openerp-server "
            "--database=oerp61-elec --update=all --stop-after-init")
    logger.info("Update completed")


def restart_erp():
    run("supervisorctl restart demo-crm")


@hipfab.hipchat(room='Devel')
def deploy():
    logger.info("Deploying...")
    from_version = last_version()
    if not has_changes(from_version):
        logger.info("No changes detected")
        return
    new_version = upload_version(from_version, patch=True)
    export_patches(from_version, new_version)
    upload_patches(new_version)
    apply_remote_patches(new_version)
    set_remote_version(new_version)
    update_all()
    restart_erp()
    logger.info('Deploy succesfull')