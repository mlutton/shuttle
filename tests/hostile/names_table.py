"""File names that break careless code: one row each, a short label saying what it attacks.

A row is a dict:
- label: what the name attacks.
- name: the name as text. A name that is not valid UTF-8 is carried with surrogateescape
  (os.fsdecode of the bytes), as every script in checks/ carries it.
- path: True when the name is already a path of several parts (a guard-folder look-alike, an
  empty component); a test that wants "a file in a guard folder" puts a folder in front of
  the rows where this is False and uses the rows where it is True as they are.
- holdable: whether a real (Linux) filesystem can hold it as the name of a file, and so
  whether git can carry it. A test that touches a filesystem skips the rows where this is
  False, or where the filesystem it runs on refuses the name anyway, and says how many.
- why_not: when holdable is False, why.
- gaps: function key ("module.function") to the reason it is a known gap there: that function
  is known to fail this row's invariant, and the test says so instead of weakening the
  invariant. A test also fails when a marked gap stops being one, so the mark cannot go stale.
"""

COVERAGE_GAP = {
    "report.coverage_config": (
        "report.coverage_config writes text that cannot be encoded as UTF-8 for a root or data "
        "file that is not valid UTF-8, so the report is not produced: it ends in one failure "
        "line and exit 1 (the tool fails closed; no TOML can hold such a path)"
    )
}
LONG_NAME = "n" * 200
TOO_LONG_NAME = "n" * 300
# Written with an escape so this file itself stays valid UTF-8 text.
NOT_UTF8 = "bad\udcff\udc80name.py"  # os.fsdecode(b"bad\xff\x80name.py")

NAMES = (
    {"label": "a space", "name": "my file.py", "path": False, "holdable": True},
    {"label": "leading space", "name": " lead.py", "path": False, "holdable": True},
    {"label": "trailing space", "name": "trail.py ", "path": False, "holdable": True},
    {"label": "only spaces", "name": "   ", "path": False, "holdable": True},
    {"label": "a tab", "name": "tab\there.py", "path": False, "holdable": True},
    {"label": "a newline", "name": "line\nbreak.py", "path": False, "holdable": True},
    {
        "label": "a newline then markup",
        "name": "x\n# heading\n- item",
        "path": False,
        "holdable": True,
    },
    {"label": "a carriage return", "name": "cr\rx.py", "path": False, "holdable": True},
    {"label": "a CRLF pair", "name": "crlf\r\nx.py", "path": False, "holdable": True},
    {"label": "a backtick", "name": "a`b.py", "path": False, "holdable": True},
    {"label": "three backticks", "name": "```", "path": False, "holdable": True},
    {
        "label": "a run of backticks longer than any fence",
        "name": "`" * 12 + "x",
        "path": False,
        "holdable": True,
    },
    {
        "label": "a fence-like name with a newline",
        "name": "x\n```\n# injected",
        "path": False,
        "holdable": True,
    },
    {"label": "tildes", "name": "~~~", "path": False, "holdable": True},
    {"label": "leading dash", "name": "-rf.py", "path": False, "holdable": True},
    {"label": "two leading dashes", "name": "--help", "path": False, "holdable": True},
    {"label": "leading hash", "name": "#heading.py", "path": False, "holdable": True},
    {"label": "four leading spaces", "name": "    code.py", "path": False, "holdable": True},
    {"label": "a pipe", "name": "a|b.py", "path": False, "holdable": True},
    {"label": "angle brackets", "name": "a<b>c.py", "path": False, "holdable": True},
    {
        "label": "an HTML tag",
        "name": "<img src=x onerror=alert(1)>.py",
        "path": False,
        "holdable": True,
    },
    {"label": "an HTML comment", "name": "<!--x-->.py", "path": False, "holdable": True},
    {"label": "a backslash", "name": "back\\slash.py", "path": False, "holdable": True},
    {"label": "a literal backslash n", "name": "back\\nslash.py", "path": False, "holdable": True},
    {"label": "a literal backslash x", "name": "literal\\x01.py", "path": False, "holdable": True},
    {
        "label": "a literal backslash u",
        "name": "literal\\u0085.py",
        "path": False,
        "holdable": True,
    },
    {"label": "single and double quotes", "name": "q'u\"o.py", "path": False, "holdable": True},
    {
        "label": "a command substitution",
        "name": "$(touch pwned).py",
        "path": False,
        "holdable": True,
    },
    {"label": "a semicolon", "name": "a;b.py", "path": False, "holdable": True},
    {"label": "a backquoted command", "name": "`id`;rm.py", "path": False, "holdable": True},
    {"label": "a variable", "name": "$HOME.py", "path": False, "holdable": True},
    {"label": "glob characters", "name": "*?[a-z].py", "path": False, "holdable": True},
    {"label": "a percent and braces", "name": "100%{x}.py", "path": False, "holdable": True},
    {"label": "non-ASCII", "name": "é ü.py", "path": False, "holdable": True},
    {
        "label": "outside the basic plane",
        "name": "emoji\U0001f600.py",
        "path": False,
        "holdable": True,
    },
    {"label": "a combining character", "name": "é.py", "path": False, "holdable": True},
    {
        "label": "not valid UTF-8",
        "gaps": COVERAGE_GAP,
        "name": NOT_UTF8,
        "path": False,
        "holdable": True,
    },
    {"label": "a C1 control character", "name": "c1\x85x.py", "path": False, "holdable": True},
    {
        "label": "the C1 character U+0085 between letters",
        "name": "x\x85y",
        "path": False,
        "holdable": True,
    },
    {
        "label": "the byte 0x85 alone between letters (not valid UTF-8): a different file",
        "gaps": COVERAGE_GAP,
        "name": "x\udc85y",
        "path": False,
        "holdable": True,
    },
    {"label": "a right-to-left override", "name": "bidi‮exe.py", "path": False, "holdable": True},
    {
        "label": "bidirectional isolates and marks",
        "name": "a⁦b⁩c‏d؜.py",
        "path": False,
        "holdable": True,
    },
    {"label": "a line separator", "name": "ls x.py", "path": False, "holdable": True},
    {"label": "a paragraph separator", "name": "ps x.py", "path": False, "holdable": True},
    {"label": "a form feed", "name": "ff\x0cx.py", "path": False, "holdable": True},
    {
        "label": "a vertical tab and the file separators",
        "name": "vt\x0bx\x1c\x1d\x1e.py",
        "path": False,
        "holdable": True,
    },
    {"label": "an escape character", "name": "esc\x1b[31mred.py", "path": False, "holdable": True},
    {"label": "a delete character", "name": "del\x7fx.py", "path": False, "holdable": True},
    {"label": "invisible format characters", "name": "zw​x﻿­.py", "path": False, "holdable": True},
    {"label": "a very long name", "name": LONG_NAME, "path": False, "holdable": True},
    {
        "label": "a name past the limit of 255 bytes",
        "name": TOO_LONG_NAME,
        "path": False,
        "holdable": False,
        "why_not": "a file name is at most 255 bytes",
    },
    {"label": "a bare status letter", "name": "M", "path": False, "holdable": True},
    {
        "label": "the text of the formatter's failure line",
        "name": "x: Failed to write victim.py",
        "path": False,
        "holdable": True,
        "gaps": {
            "fixmode.failed_from_format_output": "failed_from_format_output matches the formatter's own message `Failed to write <name>: <reason>`, so a name that holds `: Failed to write victim.py` makes a file that did not fail look as if it did"
        },
    },
    {
        "label": "a file that is the victim of that line",
        "name": "victim.py",
        "path": False,
        "holdable": True,
    },
    {"label": "the marker text", "name": "# not tested: why", "path": False, "holdable": True},
    {
        "label": "a name holding the text __pycache__",
        "name": "p__pycache__q",
        "path": False,
        "holdable": True,
    },
    {"label": "a name ending .pyc", "name": "mod.pyc", "path": False, "holdable": True},
    {"label": "a dotfile", "name": ".hidden", "path": False, "holdable": True},
    {
        "label": "a name that looks like a guard folder, with a suffix",
        "name": "checks2/x",
        "path": True,
        "holdable": True,
    },
    {
        "label": "a name that looks like a hook folder, with a suffix",
        "name": ".githubx/y",
        "path": True,
        "holdable": True,
    },
    {"label": "a guard folder in another case", "name": "Checks/x", "path": True, "holdable": True},
    {
        "label": "a guard folder one level down",
        "name": "docs/checks/x",
        "path": True,
        "holdable": True,
    },
    {
        "label": "a guard file name one level down",
        "name": "docs/pyproject.toml",
        "path": True,
        "holdable": True,
    },
    {
        "label": "a document that steers agents, one level down",
        "name": "docs/CLAUDE.md",
        "path": True,
        "holdable": True,
    },
    {
        "label": "a document that steers agents, one level down, with a suffix",
        "name": "docs/AGENTS.md.bak",
        "path": True,
        "holdable": True,
    },
    {
        "label": "a document that steers agents, with a second suffix",
        "name": "docs/process.md.orig",
        "path": True,
        "holdable": True,
    },
    {
        "label": "a look-alike of the agent definitions folder",
        "name": "agents/y",
        "path": True,
        "holdable": True,
    },
    {
        "label": "a look-alike of the agent definitions folder, with a suffix",
        "name": ".claude/agentsx/y",
        "path": True,
        "holdable": True,
    },
    {"label": "a guard folder name as a file", "name": "checks", "path": False, "holdable": True},
    {
        "label": "an empty path component",
        "name": "checks//x",
        "path": True,
        "holdable": False,
        "why_not": "a path has no empty component; the filesystem folds it away",
    },
    {
        "label": "a dot component",
        "name": "a/./b",
        "path": True,
        "holdable": False,
        "why_not": "a dot component is the folder itself",
    },
    {
        "label": "the parent folder",
        "name": "..",
        "path": False,
        "holdable": False,
        "why_not": "the name of the parent folder, not a file",
    },
    {"label": "a slash inside a name part", "name": "a/b/c", "path": True, "holdable": True},
    {
        "label": "a NUL character",
        "name": "nul\x00x.py",
        "path": False,
        "holdable": False,
        "why_not": "a name cannot hold a NUL",
    },
    {
        "label": "a name containing .pyc before its suffix",
        "name": "m.pyc.py",
        "path": False,
        "holdable": True,
    },
    {
        "label": "a control character before a digit (the escape's width)",
        "name": "a\x011",
        "path": False,
        "holdable": True,
    },
    {
        "label": "the control character the width would make of it",
        "name": "a\x11",
        "path": False,
        "holdable": True,
    },
    {
        "label": "a lone high surrogate",
        "name": "lone\ud800x",
        "path": False,
        "holdable": False,
        "why_not": "the filesystem never gives a lone surrogate outside the byte range",
        "gaps": COVERAGE_GAP,
    },
    {
        "label": "a lone low surrogate outside the byte range",
        "name": "lone\udc00x",
        "path": False,
        "holdable": False,
        "why_not": "the filesystem never gives a lone surrogate outside the byte range",
        "gaps": COVERAGE_GAP,
    },
)
