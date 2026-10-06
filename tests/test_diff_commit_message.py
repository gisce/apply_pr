# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import unittest

from apply_pr.github_utils import github_diff_url


class DiffCommitMessageTest(unittest.TestCase):
    def test_full_pull_request_uses_navigable_diff_url(self):
        self.assertEqual(
            github_diff_url(181, owner='gisce', repository='apply_pr'),
            'https://github.com/gisce/apply_pr/pull/181.diff',
        )

    def test_partial_range_identifies_both_commits(self):
        self.assertEqual(
            github_diff_url(
                181,
                owner='gisce',
                repository='apply_pr',
                from_commit='1111111',
                to_commit='9999999',
            ),
            'https://github.com/gisce/apply_pr/compare/1111111...9999999.diff',
        )

    def test_partial_range_requires_both_boundaries(self):
        with self.assertRaises(ValueError):
            github_diff_url(181, from_commit='1111111')


if __name__ == '__main__':
    unittest.main()
