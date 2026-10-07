import os
import shutil
import stat
import tempfile
import unittest

from tree_copy_with_attributes import CopyResult, copy_tree


def _make_dir_pair(root: str):
    """Return a fresh (src, dst) pair of adjacent empty dirs."""
    src = os.path.join(root, "src")
    dst = os.path.join(root, "dst")
    os.makedirs(src)
    return src, dst


def _stat(path):
    """lstat, because the whole point of the library is preserving links
    themselves rather than their targets."""
    return os.lstat(path)


class CopyTreeBasicTests(unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp(prefix="tcwa_")
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

    def test_returns_copy_result_with_expected_counts(self):
        src, dst = _make_dir_pair(self._root)
        os.makedirs(os.path.join(src, "sub"))
        with open(os.path.join(src, "a.txt"), "w") as f:
            f.write("hello")
        with open(os.path.join(src, "sub", "b.txt"), "w") as f:
            f.write("world")

        result = copy_tree(src, dst)

        self.assertIsInstance(result, CopyResult)
        self.assertEqual(result.files_copied, 2)
        self.assertEqual(result.dirs_created, 2)  # root + 'sub'
        self.assertEqual(result.symlinks_copied, 0)

    def test_empty_source_directory(self):
        src, dst = _make_dir_pair(self._root)
        result = copy_tree(src, dst)
        self.assertEqual(result, CopyResult(0, 1, 0))
        self.assertTrue(os.path.isdir(dst))

    def test_preserves_regular_file_permissions_and_timestamps(self):
        src, dst = _make_dir_pair(self._root)
        p = os.path.join(src, "f.txt")
        with open(p, "w") as f:
            f.write("data")
        os.chmod(p, 0o640)
        os.utime(p, ns=(123456789000 * 1_000_000, 987654321000 * 1_000_000))

        copy_tree(src, dst)

        dst_p = os.path.join(dst, "f.txt")
        self.assertEqual(stat.S_IMODE(_stat(dst_p).st_mode), 0o640)
        self.assertEqual(_stat(dst_p).st_atime_ns, 123456789000 * 1_000_000)
        self.assertEqual(_stat(dst_p).st_mtime_ns, 987654321000 * 1_000_000)

    def test_preserves_directory_permissions_and_timestamps(self):
        src, dst = _make_dir_pair(self._root)
        sub = os.path.join(src, "sub")
        os.makedirs(sub)
        os.chmod(sub, 0o750)
        os.utime(sub, ns=(100 * 1_000_000, 200 * 1_000_000))

        copy_tree(src, dst)

        dst_sub = os.path.join(dst, "sub")
        self.assertEqual(stat.S_IMODE(_stat(dst_sub).st_mode), 0o750)
        self.assertEqual(_stat(dst_sub).st_mtime_ns, 200 * 1_000_000)

    def test_directory_mtime_survives_child_writes(self):
        """Regression guard: writing into a directory updates its mtime, so
        the library must restore directory timestamps *after* its children
        are copied."""
        src, dst = _make_dir_pair(self._root)
        sub = os.path.join(src, "sub")
        os.makedirs(sub)
        with open(os.path.join(sub, "child.txt"), "w") as f:
            f.write("x")
        os.utime(sub, ns=(555 * 1_000_000, 666 * 1_000_000))

        copy_tree(src, dst)

        self.assertEqual(_stat(os.path.join(dst, "sub")).st_mtime_ns, 666 * 1_000_000)


class SymlinkTests(unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp(prefix="tcwa_sym_")
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

    def test_symlink_to_file_is_reproduced_not_followed(self):
        src, dst = _make_dir_pair(self._root)
        target = os.path.join(src, "real.txt")
        with open(target, "w") as f:
            f.write("payload")
        link = os.path.join(src, "link.txt")
        os.symlink(target, link)

        result = copy_tree(src, dst)

        dst_link = os.path.join(dst, "link.txt")
        self.assertTrue(os.path.islink(dst_link))
        self.assertEqual(os.readlink(dst_link), target)
        self.assertEqual(result.symlinks_copied, 1)

    def test_dangling_symlink_is_preserved(self):
        src, dst = _make_dir_pair(self._root)
        link = os.path.join(src, "broken")
        os.symlink(os.path.join(src, "does_not_exist"), link)

        copy_tree(src, dst)

        dst_link = os.path.join(dst, "broken")
        self.assertTrue(os.path.islink(dst_link))
        self.assertFalse(os.path.exists(dst_link))  # target absent
        self.assertEqual(os.readlink(dst_link), os.path.join(src, "does_not_exist"))

    def test_symlink_to_directory_is_not_traversed(self):
        """A symlink to a directory must be reproduced as a symlink, not
        recursively descended into — otherwise we'd duplicate the target tree
        and silently diverge from the source layout."""
        src, dst = _make_dir_pair(self._root)
        real_dir = os.path.join(src, "realdir")
        os.makedirs(real_dir)
        with open(os.path.join(real_dir, "inside.txt"), "w") as f:
            f.write("y")
        os.symlink(real_dir, os.path.join(src, "linkdir"))

        result = copy_tree(src, dst)

        self.assertEqual(result.symlinks_copied, 1)
        self.assertEqual(result.files_copied, 1)
        self.assertEqual(result.dirs_created, 2)
        self.assertTrue(os.path.islink(os.path.join(dst, "linkdir")))

    def test_root_source_is_a_symlink(self):
        root_src = os.path.join(self._root, "realroot")
        os.makedirs(root_src)
        with open(os.path.join(root_src, "f.txt"), "w") as f:
            f.write("z")
        link_src = os.path.join(self._root, "linkroot")
        os.symlink(root_src, link_src)
        dst = os.path.join(self._root, "dst")

        copy_tree(link_src, dst)

        self.assertTrue(os.path.islink(dst))
        self.assertEqual(os.readlink(dst), root_src)


class ErrorHandlingTests(unittest.TestCase):
    def setUp(self):
        self._root = tempfile.mkdtemp(prefix="tcwa_err_")
        self.addCleanup(shutil.rmtree, self._root, ignore_errors=True)

    def test_missing_source_raises_filenotfounderror(self):
        src = os.path.join(self._root, "missing")
        dst = os.path.join(self._root, "dst")
        with self.assertRaises(FileNotFoundError):
            copy_tree(src, dst)

    def test_existing_destination_raises_fileexistserror(self):
        src, dst = _make_dir_pair(self._root)
        os.makedirs(os.path.join(src, "sub"))
        os.makedirs(dst)
        with self.assertRaises(FileExistsError):
            copy_tree(src, dst)

    def test_exist_ok_allows_existing_empty_dir(self):
        src, dst = _make_dir_pair(self._root)
        with open(os.path.join(src, "f.txt"), "w") as f:
            f.write("x")
        os.makedirs(dst)  # pre-create empty destination

        copy_tree(src, dst, exist_ok=True)

        self.assertTrue(os.path.isfile(os.path.join(dst, "f.txt")))

    def test_exist_ok_rejects_non_empty_destination(self):
        src, dst = _make_dir_pair(self._root)
        os.makedirs(os.path.join(src, "f.txt"))
        os.makedirs(dst)
        with open(os.path.join(dst, "leftover.txt"), "w") as f:
            f.write("stale")

        with self.assertRaises(FileExistsError):
            copy_tree(src, dst, exist_ok=True)


if __name__ == "__main__":
    unittest.main()
