#!/bin/sh
# Sourced by checks/all.sh and .githooks/pre-push: the one lookup of the interpreter that has the
# tools. choose_python <working tree> prints the path of that tree's .venv/bin/python, else the
# main working tree's (a linked worktree has none of its own), else nothing. The caller applies
# PYTHON first and falls back to python3 when this prints nothing.
choose_python() {
    common=$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    main=
    [ "$(basename "$common")" = .git ] && main=$(dirname "$common")
    for candidate in "$1" "$main"; do
        [ -n "$candidate" ] && [ -x "$candidate/.venv/bin/python" ] || continue
        printf '%s\n' "$candidate/.venv/bin/python"
        return
    done
}
