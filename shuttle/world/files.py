"""Files, by name: the real set."""

import contextlib
import errno
import hashlib
import os
import stat
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


FILES = FileOperations(
    read=read,
    exists=exists,
    write_new=write_new,
    link=link,
    copy=copy,
    hash=hash_of,
    remove=remove,
    usable_folder=usable_folder,
)
