"""Files, by name: the real set."""

import os

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


def remove(path: str) -> None:
    os.unlink(path)


def usable_folder(path: str) -> bool:
    return os.path.isdir(path) and os.access(path, os.W_OK | os.X_OK)


FILES = FileOperations(
    read=read,
    exists=exists,
    write_new=write_new,
    link=link,
    remove=remove,
    usable_folder=usable_folder,
)
