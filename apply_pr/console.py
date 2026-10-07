# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import sys

import six


def as_text(value):
    if isinstance(value, six.text_type):
        return value
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    try:
        return six.text_type(value)
    except (UnicodeDecodeError, UnicodeEncodeError):
        representation = repr(value)
        if isinstance(representation, six.text_type):
            return representation
        return representation.decode('utf-8', 'replace')


def console_message(message):
    message = as_text(message)
    if six.PY2:
        return message.encode('utf-8', 'replace')
    return message


def print_message(message):
    newline = b'\n' if six.PY2 else '\n'
    sys.stdout.write(console_message(message) + newline)


def log_error(logger, error, prefix=None):
    message = as_text(error)
    if prefix:
        message = '{}{}'.format(prefix, message)
    if six.PY2:
        # Python 2's logging formatter mixes bytes with Unicode and otherwise
        # attempts to encode the message as ASCII. Escape non-ASCII characters
        # for logging; console output retains the original UTF-8 message.
        logger.error(b'%s', message.encode('ascii', 'backslashreplace'))
    else:
        logger.error('%s', message)
