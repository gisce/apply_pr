# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import unittest

from apply_pr.patch_utils import filter_patch_paths


PATCH = """From abc Mon Sep 17 00:00:00 2001
Subject: [PATCH] Mixed changes

diff --git a/addons/module/model.py b/addons/module/model.py
index 1111111..2222222 100644
--- a/addons/module/model.py
+++ b/addons/module/model.py
@@ -1 +1 @@
-before
+after
diff --git a/addons/module/tests/test_model.py b/addons/module/tests/test_model.py
new file mode 100644
--- /dev/null
+++ b/addons/module/tests/test_model.py
@@ -0,0 +1 @@
+test
diff --git a/addons/module/latest.py b/addons/module/latest.py
index 3333333..4444444 100644
--- a/addons/module/latest.py
+++ b/addons/module/latest.py
@@ -1 +1 @@
-old
+new
-- 
2.39.5
"""


class PathFilterTest(unittest.TestCase):
    def test_keeps_content_when_pattern_is_not_set(self):
        self.assertEqual(filter_patch_paths(PATCH), PATCH)

    def test_excludes_matching_file_and_directory_sections(self):
        filtered = filter_patch_paths(PATCH, r'(^|/)tests?(/|$)')

        self.assertIn('addons/module/model.py', filtered)
        self.assertIn('addons/module/latest.py', filtered)
        self.assertNotIn('addons/module/tests/test_model.py', filtered)

    def test_matches_both_old_and_new_paths(self):
        renamed = """diff --git a/old/tests/value.py b/new/value.py
similarity index 100%
rename from old/tests/value.py
rename to new/value.py
"""

        self.assertEqual(
            filter_patch_paths(renamed, r'(^|/)tests?(/|$)'),
            '',
        )

    def test_supports_quoted_paths(self):
        quoted = """diff --git \"a/docs/old file.txt\" \"b/tests/new file.txt\"
similarity index 100%
"""

        self.assertEqual(filter_patch_paths(quoted, 'tests'), '')


if __name__ == '__main__':
    unittest.main()
