# -*- coding: utf-8 -*-

from contextlib import contextmanager
import importlib
import sys

from mock import Mock, call, patch


class CommandResult(str):

    def __new__(cls, value, failed=False):
        result = str.__new__(cls, value)
        result.failed = failed
        return result


@contextmanager
def warn_only_settings(**kwargs):
    assert kwargs == {'warn_only': True}
    yield


def load_fabfile():
    fake_fabric = {
        name: module for name, module in sys.modules.items()
        if name == 'fabric' or name.startswith('fabric.')
    }
    for name in fake_fabric:
        sys.modules.pop(name, None)
    try:
        sys.modules.pop('apply_pr.fabfile', None)
        return importlib.import_module('apply_pr.fabfile')
    finally:
        for name in list(sys.modules):
            if name == 'fabric' or name.startswith('fabric.'):
                sys.modules.pop(name, None)
        sys.modules.update(fake_fabric)


def test_restore_stash_accepts_successful_pop():
    fabfile = load_fabfile()
    sudo = Mock(side_effect=[
        CommandResult("Dropped refs/stash@{0}"),
        CommandResult(""),
    ])

    with patch.object(fabfile, 'settings', warn_only_settings), \
            patch.object(fabfile, 'sudo', sudo):
        fabfile.PatchApplier.restore_stash()

    assert sudo.call_args_list == [
        call("git stash pop"),
        call("git ls-files -u"),
    ]


def test_restore_stash_resets_conflicting_pop_and_keeps_stash():
    fabfile = load_fabfile()
    sudo = Mock(side_effect=[
        CommandResult("CONFLICT", failed=True),
        CommandResult("file.py"),
        CommandResult(""),
    ])

    with patch.object(fabfile, 'settings', warn_only_settings), \
            patch.object(fabfile, 'sudo', sudo):
        try:
            fabfile.PatchApplier.restore_stash()
        except RuntimeError as exc:
            assert str(exc) == "Unable to restore stashed changes"
        else:
            raise AssertionError("A conflicting stash pop must fail")

    assert sudo.call_args_list == [
        call("git stash pop"),
        call("git ls-files -u"),
        call("git reset --merge"),
    ]
