"""Files, by name: the real set."""

import contextlib
import errno
import fcntl
import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator, Sequence
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


def is_folder(path: str) -> bool:
    return os.path.isdir(path)


def write_new(path: str, text: str) -> None:
    with open(path, "x", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def link(existing: str, new: str) -> None:
    os.link(existing, new)


def _create(new: str, mode: int | None) -> BinaryIO:
    """A new file for writing; with `mode`, made with no wider permission bits than those, at
    creation (the umask can narrow them and nothing widens them), so there is no moment it is
    more readable."""
    if mode is None:
        return open(new, "xb")  # noqa: SIM115
    descriptor = os.open(new, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, mode)
    return os.fdopen(descriptor, "wb")


def _fill(source: BinaryIO, size: int, new: str, mode: int | None = None) -> None:
    """Copy at most `size` bytes: a file still being appended to cannot make the copy endless."""
    with _create(new, mode) as target:
        left = size
        while left > 0:
            block = source.read(min(_BLOCK, left))
            if not block:
                break
            target.write(block)
            left -= len(block)
        target.flush()
        os.fsync(target.fileno())


def _copy(existing: str, new: str, mode: int | None) -> None:
    source, size = _open_regular(existing, follow=False)
    with source:
        try:
            _fill(source, size, new, mode)
        except FileExistsError:  # the name is another's: leave it
            raise
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(new)
            raise


def copy(existing: str, new: str) -> None:
    _copy(existing, new, None)


def copy_private(existing: str, new: str) -> None:
    _copy(existing, new, 0o600)


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


def temporary_folder() -> str:
    return os.path.realpath(os.environ.get("TMPDIR") or tempfile.gettempdir())


def make_private_folder(path: str) -> None:
    os.mkdir(path, 0o700)


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


def list_names(folder: str, prefix: str) -> list[str]:
    return sorted(name for name in os.listdir(folder) if name.startswith(prefix))


def look_at(path: str) -> tuple[str, bool]:
    try:
        seen = os.lstat(path)
    except FileNotFoundError:
        return "missing", False
    mode = seen.st_mode
    kind = (
        "file"
        if stat.S_ISREG(mode)
        else "folder"
        if stat.S_ISDIR(mode)
        else "link"
        if stat.S_ISLNK(mode)
        else "other"
    )
    return kind, seen.st_uid == os.geteuid()


# The descriptor of every lock this process holds, by the name of its file. A descriptor opened
# with `O_CLOEXEC` is not inherited by a child that is started, so a child never keeps a lock alive.
_held: dict[str, int] = {}
_LOCK_TRIES = 5


def _is_the_file_at(descriptor: int, path: str) -> bool:
    """Whether the name still leads to the very file the descriptor holds (a lock taken on a file
    that was removed meanwhile protects nothing)."""
    try:
        named = os.lstat(path)
    except FileNotFoundError:
        return False
    seen = os.fstat(descriptor)
    return stat.S_ISREG(named.st_mode) and (named.st_dev, named.st_ino) == (
        seen.st_dev,
        seen.st_ino,
    )


def _nothing() -> None:
    """The default `between`: does nothing."""


def make_lock(path: str, between: Callable[[], None] = _nothing) -> None:
    """`create_lock`, with `between` called in the gap after the file is opened and before it is
    locked, which is where a sweep may lock and remove it; only a test gives it a function, to be
    in that gap at a chosen moment without relying on a race."""
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
    for _ in range(_LOCK_TRIES):
        descriptor = os.open(path, flags, 0o600)
        try:
            between()
            # This waits only while a sweep holds the file for a look; the sweep then removes it
            # (no area is beside it yet), so the name is checked again and the file made again.
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            if _is_the_file_at(descriptor, path):
                _held[path] = descriptor
                return
        except BaseException:
            os.close(descriptor)
            with contextlib.suppress(OSError):
                os.unlink(path)
            raise
        os.close(descriptor)
    raise OSError(errno.EAGAIN, "the lock file was removed each time it was made", path)


def create_lock(path: str) -> None:
    make_lock(path)


def take_lock(path: str, between: Callable[[], None] = _nothing) -> bool:
    """`try_lock`, with `between` called after the file is opened and before it is locked and
    checked against the name; only a test gives it a function (see `make_lock`)."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENXIO):  # a link met, a pipe nobody holds
            raise NotARegularFile(error.errno, "not a regular file", path) from error
        raise
    try:
        _must_be_regular(os.fstat(descriptor).st_mode, path)
        between()
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return False
        if not _is_the_file_at(descriptor, path):
            raise FileNotFoundError(errno.ENOENT, "the name no longer leads to this file", path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        raise
    _held[path] = descriptor
    return True


def try_lock(path: str) -> bool:
    return take_lock(path)


def release_lock(path: str, remove: bool) -> None:
    descriptor = _held.pop(path, None)
    try:
        if remove:
            os.unlink(path)  # while the lock is still held
    finally:
        if descriptor is not None:
            os.close(descriptor)


FILES = FileOperations(
    read=read,
    read_lines=read_lines,
    exists=exists,
    is_folder=is_folder,
    write_new=write_new,
    link=link,
    copy=copy,
    copy_private=copy_private,
    hash=hash_of,
    remove=remove,
    usable_folder=usable_folder,
    temporary_folder=temporary_folder,
    make_private_folder=make_private_folder,
    make_folders=make_folders,
    copy_path=copy_path,
    make_writable=make_writable,
    remove_tree=remove_tree,
    create_lock=create_lock,
    try_lock=try_lock,
    release_lock=release_lock,
    list_names=list_names,
    look_at=look_at,
)
