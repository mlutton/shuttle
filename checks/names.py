"""File names are data. This turns one into a single line of text that cannot be misread."""

# Bidirectional controls and line/paragraph separators: shown as escapes so a name cannot be
# visually reordered or broken across lines.
_INVISIBLE = {
    0x061C,
    0x200E,
    0x200F,
    0x2028,
    0x2029,
    *range(0x202A, 0x202F),
    *range(0x2066, 0x206A),
}


def escape_char(char: str) -> str:
    code = ord(char)
    if char == "\\":
        return "\\\\"
    if char == "\n":
        return "\\n"
    if char == "\t":
        return "\\t"
    if code < 0x20 or 0x7F <= code <= 0x9F:
        return f"\\x{code:02x}"
    if 0xDC80 <= code <= 0xDCFF:  # a byte that was not valid UTF-8, kept by surrogateescape
        return f"\\x{code - 0xDC00:02x}"
    if code in _INVISIBLE or 0xD800 <= code <= 0xDFFF:
        return f"\\u{code:04x}"
    return char


def escape_name(name: str) -> str:
    """Backslash, control characters (a newline, say), bidirectional controls and bytes that
    are not valid UTF-8 become escapes; the rest is kept. The result is safe to print."""
    return "".join(escape_char(char) for char in name)
