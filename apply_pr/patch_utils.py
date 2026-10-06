# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import re
import shlex

import six


def _diff_paths(diff_header):
    """Return normalized paths from a ``diff --git`` header."""
    if six.PY2 and isinstance(diff_header, six.text_type):
        diff_header = diff_header.encode('utf-8')
    try:
        parts = shlex.split(diff_header.strip())
    except ValueError:
        return []
    if len(parts) != 4 or parts[:2] != ['diff', '--git']:
        return []
    return [path[2:] if path.startswith(('a/', 'b/')) else path
            for path in parts[2:]]


def filter_patch_paths(content, skip_directory_pattern=None):
    """Remove diff sections whose old or new path matches a regex pattern."""
    if not skip_directory_pattern:
        return content
    pattern = re.compile(skip_directory_pattern)
    starts = [match.start() for match in re.finditer(
        r'^diff --git ', content, re.MULTILINE
    )]
    if not starts:
        return content
    sections = [content[:starts[0]]]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(content)
        sections.append(content[start:end])
    kept = [sections[0]]
    for section in sections[1:]:
        header = section.splitlines()[0]
        if not any(pattern.search(path) for path in _diff_paths(header)):
            kept.append(section)
    return ''.join(kept)
