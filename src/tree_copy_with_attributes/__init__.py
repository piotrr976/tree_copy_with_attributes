"""Tree Copy with Attributes.

A small, zero-dependency library for recursively copying a directory tree
while preserving Unix file metadata that :func:`shutil.copytree` drops by
default: permission bits, access/modify timestamps, and symlink identity
(rather than following links and copying their targets).
"""

from tree_copy_with_attributes.core import CopyResult, copy_tree

__all__ = ["copy_tree", "CopyResult"]
