"""Records: the shell that reads and writes the two JSON records.

The request record is claimed by creating it, which fails if it exists.
The outcome record is written under a temporary name and then linked into
place, which fails if one exists, so it is written once and never changed.
"""
import json
import os


def request_path(records_location, request_id):
    return os.path.join(records_location, "%s.request.json" % request_id)


def outcome_path(records_location, request_id):
    return os.path.join(records_location, "%s.outcome.json" % request_id)


def claim_request_record(records_location, request_id, record):
    """Create the request record. Raises FileExistsError when the id is used.

    The id is used when either record of the pair exists.
    """
    if os.path.lexists(outcome_path(records_location, request_id)):
        raise FileExistsError(outcome_path(records_location, request_id))
    with open(request_path(records_location, request_id), "x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())


def write_outcome_record(records_location, request_id, record):
    """Write the outcome record once. Raises FileExistsError when one exists.

    Returns the path.
    """
    final = outcome_path(records_location, request_id)
    temporary = "%s.tmp-%d" % (final, os.getpid())
    try:
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(record, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.link(temporary, final)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return final


def read_record(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
