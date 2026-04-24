"""Unit tests for installer attribution reading functionality."""

import json
import struct
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import pytest

from anaconda_anon_usage.attribution import (
    INSTALLER_TOKEN_FILE_NAME,
    parse_installer_attribution,
    read_installer_attribution,
    save_installer_attribution,
)


class TestParseInstallerAttribution:
    """Tests for parse_installer_attribution function."""

    def test_parse_simple(self) -> None:
        """Parse simple attribution data."""
        data = "installer_token=abc123"
        result = parse_installer_attribution(data)
        assert result["installer_token"] == "abc123"

    def test_parse_multiple_params(self) -> None:
        """Parse attribution data with multiple parameters."""
        data = "installer_token=abc123&campaign=test&source=web"
        result = parse_installer_attribution(data)
        assert result["installer_token"] == "abc123"
        assert result["campaign"] == "test"
        assert result["source"] == "web"

    def test_parse_url_encoded(self) -> None:
        """Parse URL-encoded attribution data (outer encoding)."""
        data = "installer_token%3Dabc123%26sig%3Ddef456"
        result = parse_installer_attribution(data)
        assert result["installer_token"] == "abc123"
        assert result["sig"] == "def456"

    def test_parse_with_installer_config(self) -> None:
        """Parse attribution data with installer_config."""
        config = {"v": 1, "installer_token": "token123", "ts": 1748000000}
        config_json = json.dumps(config)
        config_encoded = quote(config_json, safe="")
        config_quoted = quote(config_encoded, safe="")
        data = f"installer_token%3Dtoken123%26installer_config%3D{config_quoted}%26sig%3Dabc"
        result = parse_installer_attribution(data)
        assert result["installer_token"] == "token123"
        assert result["installer_config"] == config_json
        assert result["sig"] == "abc"

    def test_parse_empty_string(self) -> None:
        """Parse empty string returns empty dict."""
        result = parse_installer_attribution("")
        assert result == {}

    def test_parse_special_characters(self) -> None:
        """Parse attribution data with special characters."""
        # %2B decodes to space in query string context (+ means space)
        # %3D decodes to =
        data = "installer_token=abc%2B123%3D%3D"
        result = parse_installer_attribution(data)
        assert result["installer_token"] == "abc 123=="


class TestSaveInstallerAttribution:
    """Tests for save_installer_attribution function."""

    def test_saves_token_to_file(self, tmp_path: Path) -> None:
        """Verify token is saved to the correct file."""
        with patch(
            "anaconda_anon_usage.attribution.read_installer_attribution",
            return_value="installer_token=test-token-123",
        ):
            token_file = tmp_path / INSTALLER_TOKEN_FILE_NAME
            result = save_installer_attribution(Path("fake.exe"), token_file)

            assert result is True
            assert token_file.exists()
            assert token_file.read_text() == "test-token-123"

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Verify parent directories are created if they don't exist."""
        with patch(
            "anaconda_anon_usage.attribution.read_installer_attribution",
            return_value="installer_token=nested-token",
        ):
            nested_path = tmp_path / "a" / "b" / "c" / INSTALLER_TOKEN_FILE_NAME
            result = save_installer_attribution(Path("fake.exe"), nested_path)

            assert result is True
            assert nested_path.exists()
            assert nested_path.read_text() == "nested-token"

    def test_returns_false_for_empty_attribution(self, tmp_path: Path) -> None:
        """Verify returns False when attribution data is empty."""
        with patch(
            "anaconda_anon_usage.attribution.read_installer_attribution",
            return_value="",
        ):
            token_file = tmp_path / INSTALLER_TOKEN_FILE_NAME
            result = save_installer_attribution(Path("fake.exe"), token_file)

            assert result is False
            assert not token_file.exists()

    def test_raises_error_when_no_installer_token(self, tmp_path: Path) -> None:
        """Verify raises RuntimeError when installer_token is missing."""
        with patch(
            "anaconda_anon_usage.attribution.read_installer_attribution",
            return_value="campaign=test&source=web",
        ):
            token_file = tmp_path / INSTALLER_TOKEN_FILE_NAME
            with pytest.raises(RuntimeError, match="No installer_token found"):
                save_installer_attribution(Path("fake.exe"), token_file)


class TestReadInstallerAttribution:
    """Tests for read_installer_attribution function."""

    def test_raises_error_for_short_file(self, tmp_path: Path) -> None:
        """Verify raises error for file too short to have PE header."""
        short_file = tmp_path / "short.exe"
        short_file.write_bytes(b"\x00" * 0x20)

        with pytest.raises(RuntimeError, match="PE header missing"):
            read_installer_attribution(short_file)

    def test_raises_error_for_invalid_pe_signature(self, tmp_path: Path) -> None:
        """Verify raises error for invalid PE signature."""
        invalid_pe = tmp_path / "invalid.exe"
        # Create a file with enough bytes but invalid PE signature
        data = bytearray(0x100)
        # Set PE header offset at 0x3C to point to 0x40
        struct.pack_into("<I", data, 0x3C, 0x40)
        # Write invalid signature at 0x40
        data[0x40:0x44] = b"NOPE"
        invalid_pe.write_bytes(bytes(data))

        with pytest.raises(RuntimeError, match="invalid PE signature"):
            read_installer_attribution(invalid_pe)

    def test_raises_error_for_unsigned_file(self, tmp_path: Path) -> None:
        """Verify raises error when file is not signed."""
        unsigned_pe = tmp_path / "unsigned.exe"
        data = bytearray(0x200)
        # Set PE header offset
        struct.pack_into("<I", data, 0x3C, 0x40)
        # Write valid PE signature
        data[0x40:0x44] = b"PE\x00\x00"
        # Set magic number for 64-bit (0x20B)
        struct.pack_into("<H", data, 0x58, 0x20B)
        # Certificate table offset and size are 0 (not signed)
        unsigned_pe.write_bytes(bytes(data))

        with pytest.raises(RuntimeError, match="File is not signed"):
            read_installer_attribution(unsigned_pe)

    def test_raises_error_when_tag_not_found(self, tmp_path: Path) -> None:
        """Verify raises error when ANACONDA_ATTR tag is not found."""
        pe_file = tmp_path / "no_tag.exe"
        data = bytearray(0x400)
        # Set PE header offset
        struct.pack_into("<I", data, 0x3C, 0x40)
        # Write valid PE signature
        data[0x40:0x44] = b"PE\x00\x00"
        # Set magic number for 64-bit (0x20B)
        struct.pack_into("<H", data, 0x58, 0x20B)
        # Set certificate table offset (at optional_header + 144 for 64-bit)
        cert_offset = 0x300
        cert_size = 0x100
        struct.pack_into("<I", data, 0x58 + 144, cert_offset)
        struct.pack_into("<I", data, 0x58 + 148, cert_size)
        # Don't write the tag
        pe_file.write_bytes(bytes(data))

        with pytest.raises(RuntimeError, match="Could not find tag"):
            read_installer_attribution(pe_file)

    def test_reads_attribution_data_successfully(self, tmp_path: Path) -> None:
        """Verify successfully reads attribution data from valid PE file."""
        pe_file = tmp_path / "valid.exe"
        data = bytearray(0x500)
        # Set PE header offset
        struct.pack_into("<I", data, 0x3C, 0x40)
        # Write valid PE signature
        data[0x40:0x44] = b"PE\x00\x00"
        # Set magic number for 64-bit (0x20B)
        struct.pack_into("<H", data, 0x58, 0x20B)
        # Set certificate table offset and size
        cert_offset = 0x300
        cert_size = 0x200
        struct.pack_into("<I", data, 0x58 + 144, cert_offset)
        struct.pack_into("<I", data, 0x58 + 148, cert_size)
        # Write the ANACONDA_ATTR tag and attribution data
        tag = b"ANACONDA_ATTR"
        attribution = b"installer_token=test123"
        tag_offset = cert_offset + 0x10
        data[tag_offset : tag_offset + len(tag)] = tag
        data[tag_offset + len(tag) : tag_offset + len(tag) + len(attribution)] = (
            attribution
        )
        # Add null terminator
        data[tag_offset + len(tag) + len(attribution)] = 0
        pe_file.write_bytes(bytes(data))

        result = read_installer_attribution(pe_file)
        assert result == "installer_token=test123"

    def test_reads_32bit_pe_format(self, tmp_path: Path) -> None:
        """Verify successfully reads from 32-bit PE file."""
        pe_file = tmp_path / "valid32.exe"
        data = bytearray(0x500)
        # Set PE header offset
        struct.pack_into("<I", data, 0x3C, 0x40)
        # Write valid PE signature
        data[0x40:0x44] = b"PE\x00\x00"
        # Set magic number for 32-bit (0x10B)
        struct.pack_into("<H", data, 0x58, 0x10B)
        # Set certificate table offset and size (at optional_header + 128 for 32-bit)
        cert_offset = 0x300
        cert_size = 0x200
        struct.pack_into("<I", data, 0x58 + 128, cert_offset)
        struct.pack_into("<I", data, 0x58 + 132, cert_size)
        # Write the ANACONDA_ATTR tag and attribution data
        tag = b"ANACONDA_ATTR"
        attribution = b"installer_token=test32bit"
        tag_offset = cert_offset + 0x10
        data[tag_offset : tag_offset + len(tag)] = tag
        data[tag_offset + len(tag) : tag_offset + len(tag) + len(attribution)] = (
            attribution
        )
        data[tag_offset + len(tag) + len(attribution)] = 0
        pe_file.write_bytes(bytes(data))

        result = read_installer_attribution(pe_file)
        assert result == "installer_token=test32bit"

    def test_raises_error_for_unknown_pe_format(self, tmp_path: Path) -> None:
        """Verify raises error for unknown PE magic number."""
        pe_file = tmp_path / "unknown.exe"
        data = bytearray(0x200)
        # Set PE header offset
        struct.pack_into("<I", data, 0x3C, 0x40)
        # Write valid PE signature
        data[0x40:0x44] = b"PE\x00\x00"
        # Set unknown magic number
        struct.pack_into("<H", data, 0x58, 0x999)
        pe_file.write_bytes(bytes(data))

        with pytest.raises(ValueError, match="Unknown PE format"):
            read_installer_attribution(pe_file)
