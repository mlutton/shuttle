"""Files, by name: the real set."""

import contextlib
import errno
import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Sequence
from typing import BinaryIO

from shuttle.core.shapes import FileOperations, NotARegularFile

_BLOCK = 1 << 20


def _must_be_regular(mode: int, path: str) -> None:
    if stat.S_ISDIR(mode):
        raise IsADirectoryError(errno.EISDIR, "is a folder", path)
    if not stat.S_ISREG(mode):
        raise NotARegularFile(errno.EINVAL, "not a regular file", path)


def _open_regular(path: str, follow: bool) -> tuple[BinaryIO, int]:
    """The file opened for reading, and its size now. Looks first (so a device is not opened),
    opens without waiting (so a pipe nobody writes does not block), without following a link
    unless `follow`, and looks again at what was opened: a name swapped in between is caught."""
    _must_be_regular((os.stat if follow else os.lstat)(path).st_mode, path)
    flags = os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | (0 if follow else os.O_NOFOLLOW)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENXIO):  # a link met, a socket or a pipe nobody holds
            raise NotARegularFile(error.errno, "not a regular file", path) from error
        raise
    try:
        seen = os.fstat(descriptor)
        _must_be_regular(seen.st_mode, path)
        return os.fdopen(descriptor, "rb"), seen.st_size
    except BaseException:
        os.close(descriptor)
        raise


def read(path: str) -> bytes:
    source, _ = _open_regular(path, follow=True)
    with source:
        return source.read()


def _lines(source: BinaryIO, limit: int) -> Iterator[tuple[bytes, bool]]:
    with source:
        while True:
            chunk = source.readline(limit + 1)  # memory is bounded by the limit, not by the file
            if not chunk:
                return
            if len(chunk) <= limit or chunk.endswith(b"\n"):
                yield chunk.removesuffix(b"\n"), False
                continue
            yield chunk[:limit], True
            while chunk and not chunk.endswith(b"\n"):  # skip the rest of the line in blocks
                chunk = source.readline(_BLOCK)


def read_lines(path: str, limit: int) -> Iterator[tuple[bytes, bool]]:
    source, _ = _open_regular(path, follow=True)
    return _lines(source, limit)


def exists(path: str) -> bool:
    return os.path.lexists(path)


def write_new(path: str, text: str) -> None:
    with open(path, "x", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def link(existing: str, new: str) -> None:
    os.link(existing, new)


def _fill(source: BinaryIO, size: int, new: str) -> None:
    """Copy at most `size` bytes: a file still being appended to cannot make the copy endless."""
    with open(new, "xb") as target:
        left = size
        while left > 0:
            block = source.read(min(_BLOCK, left))
            if not block:
                break
            target.write(block)
            left -= len(block)
        target.flush()
        os.fsync(target.fileno())


def copy(existing: str, new: str) -> None:
    source, size = _open_regular(existing, follow=False)
    with source:
        try:
            _fill(source, size, new)
        except FileExistsError:  # the name is another's: leave it
            raise
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(new)
            raise


def hash_of(path: str) -> str:
    digest = hashlib.sha256()
    source, _ = _open_regular(path, follow=True)
    with source:
        for block in iter(lambda: source.read(_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def remove(path: str) -> None:
    os.unlink(path)


def usable_folder(path: str) -> bool:
    return os.path.isdir(path) and os.access(path, os.W_OK | os.X_OK)


def make_temporary_folder(prefix: str) -> str:
    return os.path.realpath(tempfile.mkdtemp(prefix=prefix, dir=os.environ.get("TMPDIR") or None))


def make_folders(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _copy_folder(existing: str, new: str, left_out: frozenset[str], below: str) -> None:
    os.mkdir(new)
    with os.scandir(existing) as entries:
        found = sorted(entries, key=lambda entry: entry.name)
    for entry in found:
        name = below + entry.name
        if name in left_out or entry.is_symlink():
            continue
        target = os.path.join(new, entry.name)
        if entry.is_dir(follow_symlinks=False):
            _copy_folder(entry.path, target, left_out, name + "/")
        elif entry.is_file(follow_symlinks=False):
            copy(entry.path, target)


def copy_path(existing: str, new: str, left_out: Sequence[str]) -> None:
    if not os.path.isdir(existing) or os.path.islink(existing):
        copy(existing, new)
        return
    if os.path.lexists(new):
        raise FileExistsError(errno.EEXIST, "name is there", new)
    try:
        _copy_folder(existing, new, frozenset(left_out), "")
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise


def share_by_link(existing: str, new: str) -> None:
    os.stat(existing)  # looks, never opens: FileNotFoundError when it is not there
    os.symlink(existing, new)


def _add_owner_write(path: str, mode: int) -> None:
    os.chmod(path, mode | stat.S_IWUSR | (stat.S_IXUSR if stat.S_ISDIR(mode) else 0))


def make_writable(path: str) -> None:
    mode = os.lstat(path).st_mode
    if stat.S_ISLNK(mode):
        raise NotARegularFile(errno.EINVAL, "a link is not followed", path)
    _add_owner_write(path, stat.S_IMODE(mode))
    for folder, names, files in os.walk(path):
        for name in [*names, *files]:
            below = os.path.join(folder, name)
            seen = os.lstat(below).st_mode
            if not stat.S_ISLNK(seen):
                _add_owner_write(below, stat.S_IMODE(seen))


def remove_tree(path: str) -> None:
    if os.path.islink(path) or not os.path.isdir(path):
        os.lstat(path)  # FileNotFoundError when nothing is there
        raise NotADirectoryError(errno.ENOTDIR, "not a folder", path)
    for folder, names, _ in os.walk(path):
        for name in [".", *names]:
            below = os.path.join(folder, name)
            if not os.path.islink(below):
                os.chmod(below, stat.S_IMODE(os.lstat(below).st_mode) | stat.S_IRWXU)
    shutil.rmtree(path)


FILES = FileOperations(
    read=read,
    read_lines=read_lines,
    exists=exists,
    write_new=write_new,
    link=link,
    copy=copy,
    hash=hash_of,
    remove=remove,
    usable_folder=usable_folder,
    make_temporary_folder=make_temporary_folder,
    make_folders=make_folders,
    copy_path=copy_path,
    share_by_link=share_by_link,
    make_writable=make_writable,
    remove_tree=remove_tree,
)
