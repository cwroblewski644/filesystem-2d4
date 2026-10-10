# Filesystem Quota Checker

Computes per-user or per-group disk usage by walking a directory tree and summing `st_uid` or `st_gid` ownership of every entry, including the root directory itself.

```python
import os
import tempfile

from filesystem_quota_checker import QuotaChecker

with tempfile.TemporaryDirectory() as path:
    open(os.path.join(path, "a.txt"), "w").write("hello")
    checker = QuotaChecker(owner_key="uid")
    for result in checker.check(path):
        print(result.owner, result.file_count, result.allocated_bytes)

    # single owner
    r = checker.check_owner(path, os.getuid())
    print(r.total_bytes, r.total_blocks)
```

`UsageResult` fields: `owner`, `file_count`, `total_bytes`, `total_blocks`, and the `allocated_bytes` property (`total_blocks * 512`). Results are sorted by owner id.

## Why this exists

Real quota enforcement belongs to the filesystem, but there are times you need a read-only accounting pass over an arbitrary tree without root privileges or quota syscalls — auditing a subtree, building usage reports, or attributing growth to specific uids. This library does exactly that walk and nothing more. It uses `os.lstat` so symlinks are never followed, meaning a link whose target lives outside the tree does not contaminate the tally. Hard links are counted once per directory entry they appear under; deduplicating them across a whole tree is expensive and rarely what accounting wants.

## Edge you will hit

The tests assert exact `total_blocks` sums and therefore need a filesystem where `st_blocks` is meaningful (ext4, xfs, tmpfs in many configurations). Running on a filesystem that reports zero `st_blocks` for small files will cause the block-counting assertions to fail. The library itself works regardless — only the tests are strict about block semantics.
