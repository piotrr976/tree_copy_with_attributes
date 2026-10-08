# Tree Copy with Attributes

Recursively copies a directory tree while preserving Unix file metadata that `shutil.copytree` drops by default: permission bits, access/modify timestamps, and the identity of symbolic links (they are reproduced as links rather than followed into their targets).

```python
import os
import tempfile
from tree_copy_with_attributes import copy_tree

with tempfile.TemporaryDirectory() as root:
    src = os.path.join(root, "src")
    dst = os.path.join(root, "dst")
    os.makedirs(src)
    with open(os.path.join(src, "f.txt"), "w") as f:
        f.write("x")
    result = copy_tree(src, dst)
    print(result.files_copied, result.dirs_created, result.symlinks_copied)
```

## Why this exists

`shutil.copytree(copy2=True)` preserves timestamps and permissions for regular files but still dereferences symlinks unless you remember to pass `symlinks=True`, and those two options interact awkwardly when a tree mixes real files, real directories, and links that point at each other. This library makes one decision and sticks to it: every entry is copied with `lstat`, so symlinks are always reproduced as symlinks and every object's own metadata is applied to the copy.

## The awkward edge you will hit

`exist_ok=True` only accepts a destination that is an **empty** directory. A non-empty directory is rejected even with `exist_ok`, because merging into existing trees would require deciding how to reconcile conflicting permissions and timestamps — a problem this library deliberately does not solve. If you need merge semantics, delete the destination first or use a different tool.

Unsupported file types (device nodes, fifos, sockets) raise `ValueError`; copying them correctly typically requires root and is outside the scope of a pure-Python standard-library implementation.
