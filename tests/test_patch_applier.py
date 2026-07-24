# -*- coding: utf-8 -*-

from contextlib import contextmanager

from mock import Mock, call, patch

from apply_pr.fabfile import PatchApplier


class CommandResult(str):

    def __new__(cls, value, failed=False):
        result = str.__new__(cls, value)
        result.failed = failed
        return result


@contextmanager
def warn_only_settings(**kwargs):
    assert kwargs == {'warn_only': True}
    yield


def test_restore_stash_accepts_successful_pop():
    sudo = Mock(side_effect=[
        CommandResult("Dropped refs/stash@{0}"),
        CommandResult(""),
    ])

    with patch('apply_pr.fabfile.settings', warn_only_settings), \
            patch('apply_pr.fabfile.sudo', sudo):
        PatchApplier.restore_stash()

    assert sudo.call_args_list == [
        call("git stash pop"),
        call("git ls-files -u"),
    ]


def test_restore_stash_resets_conflicting_pop_and_keeps_stash():
    sudo = Mock(side_effect=[
        CommandResult("CONFLICT", failed=True),
        CommandResult("file.py"),
        CommandResult(""),
    ])

    with patch('apply_pr.fabfile.settings', warn_only_settings), \
            patch('apply_pr.fabfile.sudo', sudo):
        try:
            PatchApplier.restore_stash()
        except RuntimeError as exc:
            assert str(exc) == "Unable to restore stashed changes"
        else:
            raise AssertionError("A conflicting stash pop must fail")

    assert sudo.call_args_list == [
        call("git stash pop"),
        call("git ls-files -u"),
        call("git reset --merge"),
    ]
