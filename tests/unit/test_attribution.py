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
    read_installer_attribution_from_env,
    read_installer_attribution_from_sh_file,
    read_installer_attribution_pkg,
    read_installer_attribution_sh,
    read_installer_attribution_windows,
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


class TestReadInstallerAttributionWindows:
    """Tests for read_installer_attribution_windows function (PE files)."""

    def test_raises_error_for_short_file(self, tmp_path: Path) -> None:
        """Verify raises error for file too short to have PE header."""
        short_file = tmp_path / "short.exe"
        short_file.write_bytes(b"\x00" * 0x20)

        with pytest.raises(RuntimeError, match="PE header missing"):
            read_installer_attribution_windows(short_file)

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
            read_installer_attribution_windows(invalid_pe)

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
            read_installer_attribution_windows(unsigned_pe)

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
            read_installer_attribution_windows(pe_file)

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

        result = read_installer_attribution_windows(pe_file)
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

        result = read_installer_attribution_windows(pe_file)
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
            read_installer_attribution_windows(pe_file)


class TestReadInstallerAttributionShellScript:
    """Tests for shell script (.sh) attribution reading."""

    def test_reads_from_env_variable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify reads attribution from ANACONDA_ATTR env variable."""
        monkeypatch.setenv("ANACONDA_ATTR", "installer_token=env-token-123")
        result = read_installer_attribution_from_env()
        assert result == "installer_token=env-token-123"

    def test_returns_none_when_env_not_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify returns None when ANACONDA_ATTR is not set."""
        monkeypatch.delenv("ANACONDA_ATTR", raising=False)
        result = read_installer_attribution_from_env()
        assert result is None

    def test_reads_from_sh_file_single_quotes(self, tmp_path: Path) -> None:
        """Verify reads attribution from shell script with single quotes."""
        sh_file = tmp_path / "installer.sh"
        sh_file.write_text("""#!/bin/sh
export INSTALLER_NAME='Anaconda3'
export INSTALLER_TYPE="SH"
export ANACONDA_ATTR='installer_token=file-token-456'
unset CONDARC
exit 0
@@END_HEADER@@
BINARY_DATA
""")
        result = read_installer_attribution_from_sh_file(sh_file)
        assert result == "installer_token=file-token-456"

    def test_reads_from_sh_file_double_quotes(self, tmp_path: Path) -> None:
        """Verify reads attribution from shell script with double quotes."""
        sh_file = tmp_path / "installer.sh"
        sh_file.write_text("""#!/bin/sh
export INSTALLER_TYPE="SH"
export ANACONDA_ATTR="installer_token=double-quote-token"
exit 0
""")
        result = read_installer_attribution_from_sh_file(sh_file)
        assert result == "installer_token=double-quote-token"

    def test_returns_none_when_no_attr_in_file(self, tmp_path: Path) -> None:
        """Verify returns None when ANACONDA_ATTR not in file."""
        sh_file = tmp_path / "installer.sh"
        sh_file.write_text("""#!/bin/sh
export INSTALLER_TYPE="SH"
exit 0
""")
        result = read_installer_attribution_from_sh_file(sh_file)
        assert result is None

    def test_sh_reader_prefers_env_over_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify sh reader prefers env variable over file parsing."""
        monkeypatch.setenv("ANACONDA_ATTR", "installer_token=from-env")
        sh_file = tmp_path / "installer.sh"
        sh_file.write_text("""#!/bin/sh
export ANACONDA_ATTR='installer_token=from-file'
""")
        result = read_installer_attribution_sh(sh_file)
        assert result == "installer_token=from-env"

    def test_sh_reader_falls_back_to_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify sh reader falls back to file when env not set."""
        monkeypatch.delenv("ANACONDA_ATTR", raising=False)
        sh_file = tmp_path / "installer.sh"
        sh_file.write_text("""#!/bin/sh
export ANACONDA_ATTR='installer_token=fallback-token'
""")
        result = read_installer_attribution_sh(sh_file)
        assert result == "installer_token=fallback-token"


class TestReadInstallerAttributionPkg:
    """Tests for macOS .pkg attribution reading."""

    def test_reads_attribution_from_pkg_trailing_data(self, tmp_path: Path) -> None:
        """Verify reads attribution from pkg trailing data."""
        pkg_file = tmp_path / "installer.pkg"
        # Create minimal xar file with trailing attribution
        xar_content = b"xar!" + b"\x00" * 100 + b"PKG_CONTENT_HERE"
        attribution = b"ANACONDA_ATTRinstaller_token=pkg-token-789"
        pkg_file.write_bytes(xar_content + attribution)

        result = read_installer_attribution_pkg(pkg_file)
        assert result == "installer_token=pkg-token-789"

    def test_returns_none_for_invalid_xar_magic(self, tmp_path: Path) -> None:
        """Verify returns None for file without xar magic."""
        pkg_file = tmp_path / "not_a_pkg.pkg"
        pkg_file.write_bytes(b"NOT_XAR" + b"\x00" * 100)

        result = read_installer_attribution_pkg(pkg_file)
        assert result is None

    def test_returns_none_when_no_marker(self, tmp_path: Path) -> None:
        """Verify returns None when ANACONDA_ATTR marker not found."""
        pkg_file = tmp_path / "no_attr.pkg"
        pkg_file.write_bytes(b"xar!" + b"\x00" * 100 + b"NO_ATTRIBUTION_HERE")

        result = read_installer_attribution_pkg(pkg_file)
        assert result is None

    def test_handles_complex_attribution_data(self, tmp_path: Path) -> None:
        """Verify handles complex URL-encoded attribution data."""
        pkg_file = tmp_path / "complex.pkg"
        xar_content = b"xar!" + b"\x00" * 50
        attribution_data = (
            "installer_token%3DaBcDeFgHiJkLmNoP%26"
            "installer_config%3D%257B%2522v%2522%253A1%257D%26"
            "sig%3Dabc123"
        )
        pkg_file.write_bytes(
            xar_content + b"ANACONDA_ATTR" + attribution_data.encode("utf-8")
        )

        result = read_installer_attribution_pkg(pkg_file)
        assert result == attribution_data


class TestReadInstallerAttributionDispatcher:
    """Tests for the main read_installer_attribution dispatcher."""

    def test_returns_none_for_nonexistent_file(self, tmp_path: Path) -> None:
        """Verify returns None for file that doesn't exist."""
        result = read_installer_attribution(tmp_path / "nonexistent.exe")
        assert result is None

    def test_dispatches_to_pkg_reader(self, tmp_path: Path) -> None:
        """Verify .pkg files use pkg reader."""
        pkg_file = tmp_path / "test.pkg"
        pkg_file.write_bytes(
            b"xar!" + b"\x00" * 50 + b"ANACONDA_ATTRinstaller_token=pkg"
        )

        result = read_installer_attribution(pkg_file)
        assert result == "installer_token=pkg"

    def test_dispatches_to_sh_reader(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify .sh files use shell script reader."""
        monkeypatch.delenv("ANACONDA_ATTR", raising=False)
        sh_file = tmp_path / "test.sh"
        sh_file.write_text("export ANACONDA_ATTR='installer_token=sh'\n")

        result = read_installer_attribution(sh_file)
        assert result == "installer_token=sh"

    def test_dispatches_to_windows_reader_with_platform_override(
        self, tmp_path: Path
    ) -> None:
        """Verify Windows reader used when platform='windows' is specified."""
        pe_file = tmp_path / "test.exe"
        data = bytearray(0x500)
        struct.pack_into("<I", data, 0x3C, 0x40)
        data[0x40:0x44] = b"PE\x00\x00"
        struct.pack_into("<H", data, 0x58, 0x20B)
        cert_offset = 0x300
        cert_size = 0x200
        struct.pack_into("<I", data, 0x58 + 144, cert_offset)
        struct.pack_into("<I", data, 0x58 + 148, cert_size)
        tag = b"ANACONDA_ATTR"
        attribution = b"installer_token=exe"
        tag_offset = cert_offset + 0x10
        data[tag_offset : tag_offset + len(tag)] = tag
        data[tag_offset + len(tag) : tag_offset + len(tag) + len(attribution)] = (
            attribution
        )
        data[tag_offset + len(tag) + len(attribution)] = 0
        pe_file.write_bytes(bytes(data))

        result = read_installer_attribution(pe_file, platform_name="windows")
        assert result == "installer_token=exe"

    def test_returns_none_on_windows_reader_exception(self, tmp_path: Path) -> None:
        """Verify returns None when Windows reader raises exception."""
        invalid_exe = tmp_path / "invalid.exe"
        invalid_exe.write_bytes(b"not a PE file")

        result = read_installer_attribution(invalid_exe)
        assert result is None

    def test_platform_override(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify platform override works."""
        monkeypatch.setenv("ANACONDA_ATTR", "installer_token=override")
        # Create a file with no extension that would normally use platform detection
        test_file = tmp_path / "installer"
        test_file.write_bytes(b"some content")

        # Override to use linux reader (which checks env var)
        result = read_installer_attribution(test_file, platform_name="linux")
        assert result == "installer_token=override"
