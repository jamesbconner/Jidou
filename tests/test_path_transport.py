"""Tests for jidou.services.path_transport."""

from jidou.services.path_transport import (
    decode_path_bytes,
    decode_path_bytes_for_display,
    encode_path_bytes,
)


class TestEncodePathBytes:
    def test_plain_ascii_path_is_unchanged(self) -> None:
        assert encode_path_bytes("/media/show/ep01.mkv") == "/media/show/ep01.mkv"

    def test_valid_unicode_is_unchanged(self) -> None:
        # Genuinely valid UTF-8 non-ASCII characters (accented, CJK, emoji)
        # are NOT surrogate-escaped by Python and must pass through untouched.
        path = "/media/Amélie/第一話 🎬.mkv"
        assert encode_path_bytes(path) == path

    def test_surrogate_escaped_byte_is_percent_encoded(self) -> None:
        # \udce9 is how Python surrogateescape-decodes raw byte 0xE9.
        path = "Show.S01E01.Am\udce9lie.mkv"
        assert encode_path_bytes(path) == "Show.S01E01.Am%E9lie.mkv"

    def test_multiple_surrogate_bytes(self) -> None:
        path = "\udc80\udcff"
        assert encode_path_bytes(path) == "%80%FF"

    def test_literal_percent_is_escaped_to_avoid_decode_ambiguity(self) -> None:
        assert encode_path_bytes("50% Off.mkv") == "50%25 Off.mkv"

    def test_empty_string(self) -> None:
        assert encode_path_bytes("") == ""

    def test_output_always_encodes_as_utf8(self) -> None:
        path = "Show.S01E01.Am\udce9lie.mkv"
        encode_path_bytes(path).encode("utf-8")  # must not raise


class TestDecodePathBytes:
    def test_plain_ascii_path_is_unchanged(self) -> None:
        assert decode_path_bytes("/media/show/ep01.mkv") == "/media/show/ep01.mkv"

    def test_valid_unicode_is_unchanged(self) -> None:
        path = "/media/Amélie/第一話 🎬.mkv"
        assert decode_path_bytes(path) == path

    def test_percent_encoded_byte_restores_surrogate(self) -> None:
        assert decode_path_bytes("Show.S01E01.Am%E9lie.mkv") == "Show.S01E01.Am\udce9lie.mkv"

    def test_escaped_percent_restores_literal(self) -> None:
        assert decode_path_bytes("50%25 Off.mkv") == "50% Off.mkv"

    def test_lowercase_hex_digits_also_decode(self) -> None:
        assert decode_path_bytes("Show.Am%e9lie.mkv") == "Show.Am\udce9lie.mkv"

    def test_trailing_percent_without_hex_pair_is_left_literal(self) -> None:
        # Not something encode_path_bytes ever produces, but decode must not
        # crash (index out of range) on a malformed/truncated input.
        assert decode_path_bytes("Show.mkv%") == "Show.mkv%"
        assert decode_path_bytes("Show.mkv%4") == "Show.mkv%4"

    def test_percent_followed_by_non_hex_is_left_literal(self) -> None:
        assert decode_path_bytes("100%wrong") == "100%wrong"


class TestRoundTrip:
    def test_encode_then_decode_recovers_original(self) -> None:
        original = "Show.S01E01.Am\udce9lie 50% done 第一話 🎬.mkv"
        assert decode_path_bytes(encode_path_bytes(original)) == original

    def test_encode_then_decode_recovers_raw_bytes_via_surrogateescape(self) -> None:
        original_bytes = b"Show.S01E01.Am\xe9lie.mkv"
        original = original_bytes.decode("utf-8", errors="surrogateescape")
        round_tripped = decode_path_bytes(encode_path_bytes(original))
        assert round_tripped.encode("utf-8", errors="surrogateescape") == original_bytes


class TestDecodePathBytesForDisplay:
    def test_plain_ascii_path_is_unchanged(self) -> None:
        assert decode_path_bytes_for_display("/media/show/ep01.mkv") == "/media/show/ep01.mkv"

    def test_valid_unicode_is_unchanged(self) -> None:
        path = "/media/Amélie/第一話 🎬.mkv"
        assert decode_path_bytes_for_display(path) == path

    def test_escaped_literal_percent_is_restored(self) -> None:
        assert decode_path_bytes_for_display("100%25 Complete.mkv") == "100% Complete.mkv"

    def test_non_utf8_byte_becomes_replacement_character_not_surrogate(self) -> None:
        encoded = encode_path_bytes("Show.S01E01.Am\udce9lie.mkv")
        result = decode_path_bytes_for_display(encoded)
        assert result == "Show.S01E01.Am�lie.mkv"
        result.encode("utf-8")  # must not raise, unlike decode_path_bytes's output

    def test_output_always_encodes_as_utf8(self) -> None:
        encoded = encode_path_bytes("Am\udce9lie 100% \udcff done.mkv")
        decode_path_bytes_for_display(encoded).encode("utf-8")  # must not raise
