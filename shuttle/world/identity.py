"""Who and what: the real set."""

import os
import socket
import uuid

from shuttle.core.shapes import IdentityOperations


def host_name() -> str:
    return socket.gethostname()


def new_id() -> str:
    return uuid.uuid4().hex


def process_number() -> int:
    return os.getpid()


IDENTITY = IdentityOperations(host_name=host_name, new_id=new_id, process_number=process_number)
