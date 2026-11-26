"""What the tests that loop the tables share: checks on rendered text and a way to make files.

Not data: the tables themselves (names_table, imports_table, suppressions_table) hold none of
this. Kept here so the by-value tests and the command tests use one definition.
"""

import os
import sys
import unicodedata

# A second opinion on what must not reach a terminal or a Markdown page raw: the C0 and C1
# controls and DEL (category Cc), lone surrogates (Cs), line and paragraph separators and the
# bidirectional marks, embeddings, overrides and isolates. It does not read checks/names.py.
DIRECTION = {0x061C, 0x200E, 0x200F, 0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
NAMES_FOLDER = "names"


def unsafe(text):
    """Whether the text holds a character that must be shown as an escape."""
    return any(unicodedata.category(c) in ("Cc", "Cs") or ord(c) in DIRECTION for c in text)


def one_line(text):
    return not unsafe(text) and len(text.splitlines()) <= 1


def as_python(name):
    return name if name.endswith(".py") else name + ".py"


def create_all(root, rows, make=as_python, content="x = 1  # not tested: why\n", skip=()):
    """Make a file for each row under root/names/. Returns ({name: path relative to root},
    [(label, reason)] for each row not made). Rows the filesystem refuses are named on standard
    error with how many there were; so are rows in skip, a {label: reason} of rows the tool
    under test refuses (the caller says why)."""
    made, refused = {}, []
    for row in rows:
        if not row["holdable"]:
            refused.append((row["label"], row["why_not"]))
            continue
        if row["label"] in skip:
            refused.append((row["label"], skip[row["label"]]))
            continue
        rel = f"{NAMES_FOLDER}/{make(row['name'])}"
        full = os.path.join(root, rel)
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except (OSError, ValueError) as error:
            refused.append((row["label"], type(error).__name__))
            continue
        made[row["name"]] = rel
    if refused:
        sys.stderr.write(
            f"names table: {len(refused)} of {len(rows)} rows were not made: "
            + ", ".join(f"{label} ({why})" for label, why in refused)
            + "\n"
        )
    return made, refused
