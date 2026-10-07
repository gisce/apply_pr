# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
import shutil
import subprocess
import tempfile
import unittest

from apply_pr.patch_utils import append_pr_url


PATCH = """From abc Mon Sep 17 00:00:00 2001
From: Developer <developer@example.com>
Date: Tue, 6 Oct 2026 12:00:00 +0200
Subject: [PATCH] Preserve the original title

First paragraph of the body.

Second paragraph of the commit message.
---
 file.txt | 1 +
 1 file changed, 1 insertion(+)

diff --git a/file.txt b/file.txt
index e69de29..7898192 100644
--- a/file.txt
+++ b/file.txt
@@ -0,0 +1 @@
+content
-- 
2.39.5
"""


class AppendPrUrlTest(unittest.TestCase):
    def test_appends_url_after_multiline_message(self):
        url = 'https://github.com/gisce/erp/pull/12345'

        result = append_pr_url(PATCH, url)

        self.assertIn(
            'Second paragraph of the commit message.\n\n{}\n---\n'
            ' file.txt | 1 +'.format(url),
            result,
        )
        self.assertEqual(result.count(url), 1)
        self.assertIn('Subject: [PATCH] Preserve the original title', result)

    def test_git_am_creates_commit_with_original_message_and_url(self):
        checkout = tempfile.mkdtemp(prefix='apply-pr-message-test-')
        self.addCleanup(shutil.rmtree, checkout)
        subprocess.check_call(['git', 'init', '-q'], cwd=checkout)
        subprocess.check_call(
            ['git', 'config', 'user.name', 'Sastre Test'], cwd=checkout
        )
        subprocess.check_call(
            ['git', 'config', 'user.email', 'sastre@example.net'], cwd=checkout
        )
        open(os.path.join(checkout, 'file.txt'), 'w').close()
        subprocess.check_call(['git', 'add', 'file.txt'], cwd=checkout)
        subprocess.check_call(
            ['git', 'commit', '-q', '-m', 'Initial commit'], cwd=checkout
        )
        url = 'https://github.com/gisce/erp/pull/12345'
        patch_path = os.path.join(checkout, 'change.patch')
        with open(patch_path, 'w') as patch_file:
            patch_file.write(append_pr_url(PATCH, url))

        subprocess.check_call(['git', 'am', patch_path], cwd=checkout)

        message = subprocess.check_output(
            ['git', 'log', '-1', '--format=%B'], cwd=checkout
        ).decode('utf-8').strip()
        self.assertEqual(
            message,
            'Preserve the original title\n\n'
            'First paragraph of the body.\n\n'
            'Second paragraph of the commit message.\n\n{}'.format(url),
        )

    def test_leaves_a_plain_diff_unchanged(self):
        diff = 'diff --git a/file.txt b/file.txt\n'

        self.assertEqual(
            append_pr_url(diff, 'https://github.com/gisce/erp/pull/12345'),
            diff,
        )


if __name__ == '__main__':
    unittest.main()
