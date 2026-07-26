"""Lossless, JSON/DB-safe encoding for filesystem paths that may contain
non-UTF-8 bytes.

Some filenames on a POSIX filesystem aren't valid UTF-8 — commonly legacy
Latin-1/cp1252 names from an older Windows/NAS-authored library. Python
decodes such bytes with the ``surrogateescape`` error handler, producing
lone surrogate codepoints (U+DC80-U+DCFF) that raise ``UnicodeEncodeError``
outright the moment something tries to encode them as UTF-8 — a JSON
response, a database write.

:func:`encode_path_bytes` and :func:`decode_path_bytes` let such a path
travel losslessly through a JSON API round trip (scan response -> frontend
-> confirm request) so a file can still be correctly located on disk
afterwards, while staying human-readable for the overwhelming majority of
filenames: only genuinely non-UTF-8 bytes, and any literal ``%`` character,
are percent-escaped. Every other character — including ordinary non-ASCII
Unicode like accented letters or CJK/emoji, which *are* valid UTF-8 — passes
through unchanged.
"""

import string

_SURROGATE_LOW = 0xDC80
_SURROGATE_HIGH = 0xDCFF
_HEX_DIGITS = frozenset(string.hexdigits)


def encode_path_bytes(path: str) -> str:
    """Encode *path* so it always survives UTF-8 JSON/database storage.

    Args:
        path: A path string as produced by :class:`pathlib.Path` from a
            live filesystem read — may contain surrogateescape-decoded
            lone surrogates standing in for raw non-UTF-8 bytes.

    Returns:
        A string guaranteed to be valid, encodable Unicode, from which
        :func:`decode_path_bytes` can reconstruct the exact original path.
    """
    out: list[str] = []
    for ch in path:
        code = ord(ch)
        if _SURROGATE_LOW <= code <= _SURROGATE_HIGH:
            out.append(f"%{code - 0xDC00:02X}")
        elif ch == "%":
            out.append("%25")
        else:
            out.append(ch)
    return "".join(out)


def decode_path_bytes(path: str) -> str:
    """Reverse :func:`encode_path_bytes`, reconstructing the exact original path.

    Args:
        path: A string previously produced by :func:`encode_path_bytes`.

    Returns:
        The original path string, with any escaped bytes restored as
        surrogateescape codepoints — safe to pass to :class:`pathlib.Path`
        or ``open()``, which resolve it back to the exact original bytes on
        disk.
    """
    out: list[str] = []
    i = 0
    n = len(path)
    while i < n:
        ch = path[i]
        if ch == "%" and i + 2 < n and path[i + 1] in _HEX_DIGITS and path[i + 2] in _HEX_DIGITS:
            byte = int(path[i + 1 : i + 3], 16)
            out.append(chr(0xDC00 + byte) if byte >= 0x80 else chr(byte))
            i += 3
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def decode_path_bytes_for_display(path: str) -> str:
    """Reverse :func:`encode_path_bytes` for human display — lossy, not for filesystem use.

    Unlike :func:`decode_path_bytes`, any byte that still isn't valid UTF-8
    after decoding (a genuinely non-UTF-8 filename, as opposed to an escaped
    literal ``%``) is replaced with U+FFFD rather than preserved as a
    surrogate. The result reads naturally in an error message or a filename
    column, but is no longer guaranteed to resolve back to the real file —
    use :func:`decode_path_bytes` for anything that touches the filesystem.

    Args:
        path: A string previously produced by :func:`encode_path_bytes`.

    Returns:
        A human-readable approximation, safe to print or display anywhere.
    """
    raw = decode_path_bytes(path).encode("utf-8", errors="surrogateescape")
    return raw.decode("utf-8", errors="replace")
