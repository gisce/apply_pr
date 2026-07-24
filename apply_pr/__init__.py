import sys

if sys.version_info >= (3, 8):
    from importlib import metadata
else:
    import importlib_metadata as metadata

try:
    __version__ = metadata.version('apply_pr')
except Exception:
    __version__ = 'unknown'
