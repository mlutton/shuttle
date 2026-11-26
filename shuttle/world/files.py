"""Files, by name: the real set."""

import contextlib
import hashlib
import os
import shutil
from typing import BinaryIO

from shuttle.core.shapes import FileOperations


def read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def exists(path: str) -> bool:
    return os.path.lexists(path)


def write_new(path: str, text: str) -> None:
    with open(path, "x", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def link(existing: str, new: str) -> None:
    os.link(existing, new)


def _fill(source: BinaryIO, new: str) -> None:
    with open(new, "xb") as target:
        shutil.copyfileobj(source, target)
        target.flush()
        os.fsync(target.fileno())


def copy(existing: str, new: str) -> None:
    with open(existing, "rb") as source:
        try:
            _fill(source, new)
        except FileExistsError:  # the name is another's: leave it
            raise
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(new)
            raise


def hash_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
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
