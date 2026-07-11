"""Tests for jidou.services.sys_name.sanitize_sys_name."""

from jidou.services.sys_name import sanitize_sys_name


def test_colon_replaced_with_space() -> None:
    """A colon directly touching both neighbors becomes a single space."""
    assert sanitize_sys_name("Re:Zero") == "Re Zero"


def test_colon_already_followed_by_space_does_not_double() -> None:
    """A colon already followed by a space collapses to one space, not two."""
    assert sanitize_sys_name("Attack on Titan: Final Season") == "Attack on Titan Final Season"


def test_multiple_invalid_characters() -> None:
    """Every invalid character is replaced; runs of whitespace collapse to one."""
    assert sanitize_sys_name('Show: "Special" <Edition>') == "Show Special Edition"


def test_no_invalid_characters_unchanged() -> None:
    """A title with nothing to sanitize passes through unchanged."""
    assert sanitize_sys_name("Cowboy Bebop") == "Cowboy Bebop"


def test_leading_and_trailing_whitespace_stripped() -> None:
    """Whitespace introduced at the very start/end of the title is stripped."""
    assert sanitize_sys_name(":Show:") == "Show"


def test_all_invalid_characters_replaced() -> None:
    """Every character in the invalid set is handled, not just colon."""
    assert sanitize_sys_name(r'A\B/C:D*E?F"G<H>I|J') == "A B C D E F G H I J"
