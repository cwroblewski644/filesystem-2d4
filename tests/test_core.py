import os
import stat
import tempfile
import unittest

from filesystem_quota_checker import QuotaChecker, UsageResult, QuotaError


class QuotaCheckerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, relpath, content, uid=None):
        full = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        if uid is not None:
            os.chown(full, uid, os.stat(full).st_gid)
        return full

    def _root_blocks(self):
        return os.lstat(self.root).st_blocks

    def test_empty_directory_returns_root_only(self):
        results = QuotaChecker().check(self.root)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.owner, os.getuid())
        self.assertEqual(r.file_count, 1)
        self.assertEqual(r.total_bytes, os.lstat(self.root).st_size)
        self.assertEqual(r.total_blocks, self._root_blocks())

    def test_root_directory_itself_is_counted(self):
        # The root inode is included so its own block usage is accounted;
        # otherwise the directory holding everything is invisible in the
        # tally.
        os.chown(self.root, os.getuid(), os.stat(self.root).st_gid)
        results = QuotaChecker().check(self.root)
        owners = [r.owner for r in results]
        self.assertIn(os.getuid(), owners)
        r = next(x for x in results if x.owner == os.getuid())
        self.assertGreaterEqual(r.file_count, 1)

    def test_single_file_usage(self):
        path = self._write("a.txt", "hello world")
        st = os.lstat(path)
        results = QuotaChecker().check(self.root)
        r = next(x for x in results if x.owner == os.getuid())
        self.assertEqual(r.total_bytes, st.st_size + os.lstat(self.root).st_size)
        self.assertEqual(r.total_blocks, st.st_blocks + self._root_blocks())

    def test_multiple_files_aggregated_by_uid(self):
        p1 = self._write("a.txt", "aaaa")
        p2 = self._write("b.txt", "bbbbbbbb")
        st1 = os.lstat(p1)
        st2 = os.lstat(p2)
        results = QuotaChecker().check(self.root)
        r = next(x for x in results if x.owner == os.getuid())
        self.assertEqual(r.total_bytes, st1.st_size + st2.st_size + os.lstat(self.root).st_size)
        self.assertEqual(r.total_blocks, st1.st_blocks + st2.st_blocks + self._root_blocks())

    def test_results_sorted_by_owner(self):
        results = QuotaChecker().check(self.root)
        owners = [r.owner for r in results]
        self.assertEqual(owners, sorted(owners))

    def test_result_is_immutable(self):
        self._write("a.txt", "data")
        r = QuotaChecker().check(self.root)[0]
        with self.assertRaises((AttributeError, TypeError)):
            r.owner = 999

    def test_symlink_target_not_followed(self):
        # lstat is used so a symlink pointing outside the tree does not
        # drag external bytes into the result; only the symlink's own
        # inode blocks are counted.
        target = self._write("real.txt", "x" * 4096)
        link = os.path.join(self.root, "link.txt")
        os.symlink(target, link)
        link_st = os.lstat(link)
        results = QuotaChecker().check(self.root)
        r = next(x for x in results if x.owner == os.getuid())
        # root dir + real.txt + symlink = 3 entries minimum
        self.assertGreaterEqual(r.file_count, 3)
        self.assertEqual(r.total_blocks, link_st.st_blocks + os.lstat(target).st_blocks + self._root_blocks())

    def test_hard_link_counted_once_per_entry(self):
        # Hard links are not deduplicated across the tree; each directory
        # entry is a separate accounting unit by design.
        orig = self._write("orig.txt", "data")
        linked = os.path.join(self.root, "link.txt")
        os.link(orig, linked)
        st = os.lstat(orig)
        results = QuotaChecker().check(self.root)
        r = next(x for x in results if x.owner == os.getuid())
        # root + orig + hardlink entry
        self.assertEqual(r.file_count, 3)
        self.assertEqual(r.total_blocks, self._root_blocks() + st.st_blocks * 2)

    def test_nested_directories_walked(self):
        self._write("sub/deep/c.txt", "nested")
        results = QuotaChecker().check(self.root)
        r = next(x for x in results if x.owner == os.getuid())
        # root + sub + deep + c.txt
        self.assertEqual(r.file_count, 4)

    def test_nonexistent_root_raises_quota_error(self):
        with self.assertRaises(QuotaError):
            QuotaChecker().check(os.path.join(self.root, "does_not_exist"))

    def test_invalid_owner_key_raises_value_error(self):
        with self.assertRaises(ValueError):
            QuotaChecker(owner_key="bogus")

    def test_allocated_bytes_property(self):
        path = self._write("a.txt", "hello")
        st = os.lstat(path)
        results = QuotaChecker().check(self.root)
        r = next(x for x in results if x.owner == os.getuid())
        self.assertEqual(r.allocated_bytes, r.total_blocks * 512)
        self.assertGreater(r.allocated_bytes, 0)

    def test_check_owner_returns_single_result(self):
        self._write("a.txt", "hello")
        uid = os.getuid()
        r = QuotaChecker().check_owner(self.root, uid)
        self.assertEqual(r.owner, uid)
        self.assertGreater(r.file_count, 0)

    def test_check_owner_raises_for_missing_owner(self):
        self._write("a.txt", "hello")
        with self.assertRaises(ValueError):
            QuotaChecker().check_owner(self.root, 999999)


if __name__ == "__main__":
    unittest.main()
