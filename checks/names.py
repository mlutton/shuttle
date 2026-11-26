"""File names are data. This turns one into a single line of text that cannot be misread."""


def escape_name(name: str) -> str:
    """Backslash and control characters (a newline, say) become escapes; the rest is kept."""
    out = []
    for char in name:
        if char == "\\":
            out.append("\\\\")
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif ord(char) < 0x20 or ord(char) == 0x7F:
            out.append(f"\\x{ord(char):02x}")
        else:
            out.append(char)
    return "".join(out)
