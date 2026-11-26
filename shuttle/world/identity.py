"""Who and what: the real set."""

import socket
import uuid

from shuttle.core.shapes import IdentityOperations


def host_name() -> str:
    return socket.gethostname()


def new_id() -> str:
    return uuid.uuid4().hex


IDENTITY = IdentityOperations(host_name=host_name, new_id=new_id)
