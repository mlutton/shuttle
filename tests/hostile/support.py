"""What the tests that loop the tables share: checks on rendered text and a way to make files.

Not data: the tables themselves (names_table, imports_table, suppressions_table) hold none of
this. Kept here so the by-value tests and the command tests use one definition.
"""

import os
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
    [(label, error name)] for the rows that should have worked and did not). A row the table
    says no filesystem holds (holdable False), and a row in skip (a {label: reason} of rows the
    tool under test refuses), are left out and not reported: they are expected."""
    made, unexpected = {}, []
    for row in rows:
        if not row["holdable"] or row["label"] in skip:
            continue
        rel = f"{NAMES_FOLDER}/{make(row['name'])}"
        full = os.path.join(root, rel)
        try:
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except (OSError, ValueError) as error:
            unexpected.append((row["label"], type(error).__name__))
            continue
        made[row["name"]] = rel
    return made, unexpected


def unmade_note(unexpected):
    """One short line for a test's skip reason: how many rows this filesystem refused and the
    first few labels."""
    shown = ", ".join(label for label, _ in unexpected[:3])
    more = "..." if len(unexpected) > 3 else ""
    return (
        f"this filesystem refused {len(unexpected)} names the table says it can hold: {shown}{more}"
    )
