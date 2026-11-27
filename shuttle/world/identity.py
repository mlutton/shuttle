"""Who and what: the real set."""

import os
import pwd
import socket
import uuid

from shuttle.core.shapes import IdentityOperations


def host_name() -> str:
    return socket.gethostname()


def new_id() -> str:
    return uuid.uuid4().hex


def process_number() -> int:
    return os.getpid()


def home_folder() -> str | None:
    """The home folder in the account records, not the one the caller's `HOME` names."""
    try:
        home = pwd.getpwuid(os.getuid()).pw_dir
    except KeyError:
        return None
    return home if home.startswith("/") else None


def runtime_folder() -> str:
    """Where systemd makes the user's runtime folder, whatever `XDG_RUNTIME_DIR` says."""
    return f"/run/user/{os.getuid()}"


IDENTITY = IdentityOperations(
    host_name=host_name,
    new_id=new_id,
    process_number=process_number,
    home_folder=home_folder,
    runtime_folder=runtime_folder,
)
