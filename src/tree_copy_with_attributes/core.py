import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Union


@dataclass(frozen=True)
class CopyResult:
    """Summary of a completed :func:`copy_tree` run.

    Fields
    ------
    files_copied:
        Number of regular files copied.
    dirs_created:
        Number of directories created (the destination root counts once).
    symlinks_copied:
        Number of symbolic links re-created at the destination.
    """

    files_copied: int
    dirs_created: int
    symlinks_copied: int


class _CountingCopyTree:
    """Internal helper encapsulating the recursive walk and counters.

    Keeping state on an instance (rather than threading mutable counters
    through every recursive call) keeps the public :func:`copy_tree` signature
    clean and makes the counters trivially inspectable in tests.
    """

    __slots__ = ("_src", "_dst", "_files", "_dirs", "_links")

    def __init__(self, src: str, dst: str) -> None:
        self._src = src
        self._dst = dst
        self._files = 0
        self._dirs = 0
        self._links = 0

    def run(self) -> CopyResult:
        src_path = Path(self._src)
        dst_path = Path(self._dst)

        if not src_path.exists():
            # Use ``not exists`` rather than ``not is_dir`` so that a broken
            # symlink at the root raises our clear error instead of being
            # silently treated as a directory.
            raise FileNotFoundError(f"Source does not exist: {src_path}")

        if dst_path.exists():
            raise FileExistsError(f"Destination already exists: {dst_path}")

        self._copy_node(src_path, dst_path)
        return CopyResult(
            files_copied=self._files,
            dirs_created=self._dirs,
            symlinks_copied=self._links,
        )

    def _copy_node(self, src: Path, dst: Path) -> None:
        """Copy one filesystem object (file, dir, or symlink) to *dst*.

        ``lstat`` is used deliberately: we want to inspect the link itself
        (so we can reproduce it) rather than the object it points at.
        """

        st = os.lstat(src)

        if stat.S_ISLNK(st.st_mode):
            self._copy_symlink(src, dst, st)
        elif stat.S_ISDIR(st.st_mode):
            self._copy_dir(src, dst, st)
        elif stat.S_ISREG(st.st_mode):
            self._copy_regular_file(src, dst, st)
        else:
            # Covers fifos, sockets, block/char devices. Copying device
            # nodes generally requires root and is out of scope; failing
            # loudly is safer than silently producing an empty file.
            raise ValueError(f"Unsupported file type: {src}")

    def _copy_symlink(self, src: Path, dst: Path, st: os.stat_result) -> None:
        target = os.readlink(src)
        os.symlink(target, dst)
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns), follow_symlinks=False)
        self._links += 1

    def _copy_dir(self, src: Path, dst: Path, st: os.stat_result) -> None:
        os.mkdir(dst, mode=st.st_mode)
        # ``mkdir`` applies the process umask to *mode*, so set the real mode
        # explicitly to match the source exactly.
        os.chmod(dst, st.st_mode, follow_symlinks=False)
        self._dirs += 1

        for entry in os.listdir(src):
            self._copy_node(src / entry, dst / entry)

        # Restore directory times *after* writing its children, otherwise
        # creating those children updates the directory mtime and clobbers
        # the value we wanted to preserve.
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns), follow_symlinks=False)

    def _copy_regular_file(self, src: Path, dst: Path, st: os.stat_result) -> None:
        with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst, length=1024 * 1024)
        os.chmod(dst, st.st_mode, follow_symlinks=False)
        os.utime(dst, ns=(st.st_atime_ns, st.st_mtime_ns), follow_symlinks=False)
        self._files += 1


def copy_tree(src: Union[str, "os.PathLike[str]"], dst: Union[str, "os.PathLike[str]"], *, exist_ok: bool = False) -> CopyResult:
    """Recursively copy *src* into *dst*, preserving permissions, timestamps,
    and symlink structure.

    Parameters
    ----------
    src:
        Path to the directory tree to copy. May itself be a symlink; the link
        is reproduced at *dst*, not followed into its target.
    dst:
        Path for the new copy. Must not already exist (unless ``exist_ok``
        is true and it is an empty directory).
    exist_ok:
        When true, allows *dst* to be an existing **empty** directory; any
        other pre-existing state is still an error. This mirrors the option
        added to :func:`shutil.copytree` in 3.8 and makes idempotent
        re-runs (e.g. retrying a partially-failed copy) ergonomic.

    Returns
    -------
    CopyResult
        Counters describing what was copied.

    Raises
    ------
    FileNotFoundError
        *src* does not exist (including the broken-symlink case).
    FileExistsError
        *dst* already exists in a form not allowed by *exist_ok*.
    ValueError
        An entry of an unsupported type (device, fifo, socket) is encountered.
    """

    src_str = os.fspath(src)
    dst_str = os.fspath(dst)

    dst_path = Path(dst_str)
    if dst_path.exists():
        if not exist_ok or not dst_path.is_dir() or os.listdir(dst_path):
            raise FileExistsError(f"Destination already exists: {dst_path}")
        # Existing empty dir: remove so the fresh-copy path produces the
        # correct metadata rather than merging into the existing inode.
        dst_path.rmdir()

    return _CountingCopyTree(src_str, dst_str).run()
