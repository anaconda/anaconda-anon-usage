"""Parity tests between the Rust anaconda-anon-usage crate and the Python package.

These tests ensure that the Rust implementation produces identical token
values to the Python anaconda_anon_usage package for all token types:
c (client), s (session), e (environment), a (anaconda), o (org),
m (machine), i (installer).

The Rust binary must be built before running these tests:
    cd rust && cargo build
"""

import base64
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

from anaconda_anon_usage import __version__ as AAU_VERSION

REPO_ROOT = Path(__file__).parent.parent
VALID_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,36}$")


def _find_rust_bin() -> str:
    if env := os.environ.get("AAU_RUST_BIN"):
        return env
    ext = ".exe" if sys.platform == "win32" else ""
    for subpath in [
        f"rust/target/release/anaconda-anon-usage{ext}",
        f"rust/target/debug/anaconda-anon-usage{ext}",
    ]:
        p = REPO_ROOT / subpath
        if p.exists():
            return str(p)
    return str(REPO_ROOT / "rust" / "target" / "debug" / f"anaconda-anon-usage{ext}")


RUST_BIN = _find_rust_bin()


def _run_rust(args, env_override=None):
    """Run the Rust binary with the given arguments."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [RUST_BIN] + args,
        capture_output=True,
        text=True,
        env=env,
    )
    assert (
        result.returncode == 0
    ), f"Rust binary failed: {result.stderr}\nstdout: {result.stdout}"
    return result.stdout.strip()


def _run_rust_tokens(env_override=None, extra_args=None):
    """Run `anaconda-anon-usage` (default: token output) and return stdout."""
    args = list(extra_args) if extra_args else []
    return _run_rust(args, env_override=env_override)


def _parse_tokens(token_string):
    """Parse an AAU token string into {prefix: [values]}."""
    result = {}
    parts = token_string.split()
    # Skip past "aau/{version}" prefix
    for part in parts[1:]:
        prefix, _, value = part.partition("/")
        if len(prefix) == 1 and value:
            result.setdefault(prefix, []).append(value)
    return result


def _python_token_fresh(func_name, env_override=None):
    """Run a Python AAU token function in a fresh subprocess to avoid caching."""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    code = f"""
import os, sys
from anaconda_anon_usage import tokens
result = tokens.{func_name}
if isinstance(result, list):
    print('\\n'.join(result))
elif result is not None:
    print(result)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"Python {func_name} failed: {result.stderr}"
    return result.stdout.strip()


def _home_env(tmpdir):
    """Return env vars to override the home directory, platform-aware."""
    if sys.platform == "win32":
        return {"USERPROFILE": tmpdir, "HOME": tmpdir}
    return {"HOME": tmpdir}


def _isolated_env_for_parity(tmpdir):
    """Build an env dict that fully isolates the token search path.

    Covers:
    - $HOME (via _home_env)
    - $CONDA_PREFIX, $CONDA_ROOT, $CONDA_EXE, $CONDA_PYTHON_EXE
    - $XDG_CONFIG_HOME (redirected to nonexistent sandbox path)
    - /etc/conda, /var/lib/conda, C:/ProgramData/conda
      (via ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT)
    """
    tmpdir = str(tmpdir)
    env = _home_env(tmpdir)
    env["CONDA_PREFIX"] = ""
    env["CONDA_ROOT"] = ""
    env["CONDA_EXE"] = ""
    env["CONDA_PYTHON_EXE"] = ""
    env["XDG_CONFIG_HOME"] = str(Path(tmpdir) / "xdg")
    sys_root = Path(tmpdir) / "fake_etc_conda"
    sys_root.mkdir(exist_ok=True)
    env["ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT"] = str(sys_root)
    return env


def _isolated_home():
    """Create a temp HOME with minimal conda config to isolate token tests."""
    tmpdir = tempfile.mkdtemp()
    (Path(tmpdir) / ".conda").mkdir()
    return tmpdir


class TestVersion:
    """Verify the Rust crate version matches the Python package version."""

    def test_version_matches(self):
        """The Rust AAU_VERSION must exactly match Python's __version__."""
        rs_output = _run_rust_tokens()
        rs_aau = rs_output.split()[0]  # "aau/{version}"
        assert rs_aau.startswith("aau/"), f"Unexpected format: {rs_aau}"
        rs_version = rs_aau.split("/", 1)[1]
        assert rs_version == AAU_VERSION, (
            f"Version mismatch:\n"
            f"  Rust:   {rs_version}\n"
            f"  Python: {AAU_VERSION}"
        )

    def test_version_format_pep440(self):
        """Version should follow PEP 440 (versioneer convention).

        On a tag:         "0.7.6"
        Past a tag:       "0.7.6+3.gabcdef0"
        """
        rs_output = _run_rust_tokens()
        rs_version = rs_output.split()[0].split("/", 1)[1]
        # Must start with a digit and contain only valid PEP 440/semver chars
        assert re.match(
            r"^\d+\.\d+\.\d+(\+\d+\.g[0-9a-f]+)?$", rs_version
        ), f"Version does not match expected format: {rs_version}"


class TestTokenFormat:
    """Validate token string format."""

    def test_all_tokens_valid_format(self):
        """All tokens should match the AAU token regex."""
        rs_output = _run_rust_tokens()
        parsed = _parse_tokens(rs_output)
        for prefix, values in parsed.items():
            for value in values:
                assert VALID_TOKEN_RE.match(
                    value
                ), f"Invalid token format: {prefix}/{value}"

    def test_detail_shows_provenance(self):
        """--detail flag should show token source information."""
        output = _run_rust(["--detail"])
        assert "(client)" in output, f"Missing client provenance:\n{output}"
        assert "(session)" in output, f"Missing session provenance:\n{output}"


class TestClientToken:
    """c/ token: persisted per-installation identity."""

    def test_client_token_present(self):
        """Both Python and Rust should produce a client token."""
        rs_tokens = _parse_tokens(_run_rust_tokens())
        py_client = _python_token_fresh("client_token()")
        assert "c" in rs_tokens, "Rust missing client token"
        assert py_client, "Python missing client token"

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_client_token_reads_existing_file(self):
        """When Python creates a token + node file, Rust must return the same value.

        This is the critical node-tie parity test. Python encodes the MAC address
        using sys.byteorder; if Rust encodes it differently, it will see a "changed"
        host and regenerate the token, silently returning a different value.
        """
        tmpdir = _isolated_home()
        try:
            env = _home_env(tmpdir)
            # Let Python generate the token and node file
            py_client = _python_token_fresh("client_token()", env_override=env)
            assert py_client, "Python didn't generate a client token"

            # Verify the files Python wrote
            conda_dir = Path(tmpdir) / ".conda"
            token_file = conda_dir / "aau_token"
            host_file = conda_dir / "aau_token_host"
            assert token_file.exists(), "Python didn't write aau_token"
            assert host_file.exists(), "Python didn't write aau_token_host"
            py_node = host_file.read_text().strip()
            assert py_node, "Python wrote an empty aau_token_host"

            # Rust must return the exact same token (not regenerate)
            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_client = rs_tokens.get("c", [None])[0]
            assert rs_client == py_client, (
                f"Client token mismatch — Rust likely regenerated due to node-tie divergence:\n"
                f"  Python token: {py_client}\n"
                f"  Rust token:   {rs_client}\n"
                f"  Python node:  {py_node}\n"
                f"  aau_token:    {token_file.read_text().strip()}"
            )

            # Verify Rust didn't overwrite the host file with a different encoding
            assert (
                host_file.read_text().strip() == py_node
            ), "Rust overwrote aau_token_host with a different node encoding"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_node_string_matches_python(self):
        """Rust and Python must produce identical MAC-based node strings.

        Python: uuid._unix_getnode() -> int.to_bytes(6, sys.byteorder) -> b64
        Rust:   mac_address crate -> [u8;6] network order -> reverse on LE -> b64
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from anaconda_anon_usage.utils import _get_node_str; print(_get_node_str())",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Python _get_node_str failed: {result.stderr}"
        py_node = result.stdout.strip()
        # Rust: create a token in a temp home, then read the host file it writes
        tmpdir = _isolated_home()
        try:
            env = _home_env(tmpdir)
            _run_rust_tokens(env_override=env)
            host_file = Path(tmpdir) / ".conda" / "aau_token_host"
            assert host_file.exists(), "Rust didn't write aau_token_host"
            rs_node = host_file.read_text().strip()

            assert rs_node == py_node, (
                f"Node string mismatch (MAC byte-order encoding differs):\n"
                f"  Python: {py_node}\n"
                f"  Rust:   {rs_node}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestSessionToken:
    """s/ token: random per-process, cannot compare values."""

    def test_session_token_present(self):
        rs_tokens = _parse_tokens(_run_rust_tokens())
        assert "s" in rs_tokens, "Rust missing session token"

    def test_session_token_changes_per_invocation(self):
        t1 = _parse_tokens(_run_rust_tokens()).get("s", [None])[0]
        t2 = _parse_tokens(_run_rust_tokens()).get("s", [None])[0]
        assert t1 != t2, "Session tokens should differ between invocations"


class TestEnvironmentToken:
    """e/ token: per-conda-environment identity."""

    def test_environment_token_with_prefix(self):
        """Both should read the same pre-existing environment token."""
        with tempfile.TemporaryDirectory() as tmpdir:
            etc_dir = Path(tmpdir) / "etc"
            etc_dir.mkdir()

            known_token = _run_rust(["--random"])
            (etc_dir / "aau_token").write_text(f"{known_token}\n")

            py_token = _python_token_fresh(
                "environment_token(os.environ['CONDA_PREFIX'])",
                env_override={"CONDA_PREFIX": tmpdir},
            )
            rs_tokens = _parse_tokens(
                _run_rust_tokens(
                    env_override={"CONDA_PREFIX": tmpdir},
                    extra_args=["--prefix", tmpdir],
                )
            )

            assert (
                py_token == known_token
            ), f"Python env token: {py_token!r}, expected {known_token!r}"
            assert "e" in rs_tokens, "Rust missing environment token"
            assert (
                rs_tokens["e"][0] == known_token
            ), f"Environment token mismatch: Rust={rs_tokens.get('e')} Python={py_token}"

    def test_no_environment_token_without_prefix(self):
        """Without CONDA_PREFIX or --prefix, no e/ token should appear."""
        env = {k: v for k, v in os.environ.items() if k != "CONDA_PREFIX"}
        env["CONDA_PREFIX"] = ""  # explicitly clear
        rs_output = _run_rust([], env_override=env)
        rs_tokens = _parse_tokens(rs_output)
        assert (
            "e" not in rs_tokens
        ), f"Unexpected environment token: {rs_tokens.get('e')}"


class TestAnacondaAuthToken:
    """a/ token: extracted from caller-provided JWT."""

    @pytest.fixture(autouse=True)
    def _make_jwt(self):
        """Build a synthetic JWT with a known UUID sub claim."""
        from conftest import _keyring_data

        _, self.sub, self.jwt = _keyring_data()
        # Compute the expected token: base64url(UUID.bytes), no padding
        self.expected_token = (
            base64.urlsafe_b64encode(uuid.UUID(self.sub).bytes)
            .decode("ascii")
            .rstrip("=")
        )

    def test_anaconda_token_from_jwt(self):
        """Rust should extract the correct a/ token from a synthetic JWT."""
        rs_tokens = _parse_tokens(_run_rust_tokens(extra_args=["--jwt", self.jwt]))
        assert "a" in rs_tokens, "Rust missing anaconda auth token"
        assert rs_tokens["a"][0] == self.expected_token, (
            f"Anaconda token mismatch: Rust={rs_tokens.get('a')} "
            f"expected={self.expected_token}"
        )

    def test_anaconda_token_matches_python(self):
        """Rust and Python should extract the same a/ token from the same JWT."""
        from anaconda_anon_usage.tokens import _jwt_to_token

        py_token = _jwt_to_token(self.jwt)
        rs_tokens = _parse_tokens(_run_rust_tokens(extra_args=["--jwt", self.jwt]))
        assert "a" in rs_tokens, "Rust missing anaconda auth token"
        assert (
            py_token == rs_tokens["a"][0]
        ), f"Anaconda token mismatch: Rust={rs_tokens.get('a')} Python={py_token}"

    def test_no_jwt_means_no_anaconda_token(self):
        """Without --jwt, no a/ token should appear."""
        rs_tokens = _parse_tokens(_run_rust_tokens())
        assert (
            "a" not in rs_tokens
        ), f"a/ token present without --jwt: {rs_tokens.get('a')}"


class TestSystemTokensParity:
    """o/ m/ i/ tokens: org, machine, and installer system tokens."""

    @pytest.mark.parametrize(
        "env_var,prefix,py_func",
        [
            ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()"),
            ("ANACONDA_ANON_USAGE_MACHINE_TOKEN", "m", "machine_tokens()"),
            ("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", "i", "installer_tokens()"),
        ],
    )
    def test_env_var_single_token(self, env_var, prefix, py_func):
        """A single token via env var should appear identically in both."""
        tmpdir = _isolated_home()
        try:
            test_token = "parity-test-token-42"
            env = {**_isolated_env_for_parity(tmpdir), env_var: test_token}

            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert test_token in py_list, f"Python missing: {py_list}"
            assert test_token in rs_list, f"Rust missing: {rs_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # Regression test: specifically guards against Rust re-adding slash-splitting
    @pytest.mark.parametrize(
        "env_var,prefix,py_func",
        [
            ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()"),
            ("ANACONDA_ANON_USAGE_MACHINE_TOKEN", "m", "machine_tokens()"),
            ("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", "i", "installer_tokens()"),
        ],
    )
    def test_env_var_slash_separated_tokens(self, env_var, prefix, py_func):
        """Slash-separated tokens in env var should behave identically in both."""
        tmpdir = _isolated_home()
        try:
            env = {**_isolated_env_for_parity(tmpdir), env_var: "token-alpha/token-beta"}

            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert py_list == rs_list, (
                f"Python and Rust diverge on slash-separated input:\n"
                f"  Python: {py_list}\n"
                f"  Rust:   {rs_list}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize(
        "env_var,prefix,py_func",
        [
            ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()"),
            ("ANACONDA_ANON_USAGE_MACHINE_TOKEN", "m", "machine_tokens()"),
            ("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", "i", "installer_tokens()"),
        ],
    )
    def test_env_var_with_invalid_char_rejected_identically(self, env_var, prefix, py_func):
        """A token with invalid chars should be rejected by both implementations
        in the same way — not discarded by one and salvaged-by-splitting by the other."""
        tmpdir = _isolated_home()
        try:
            # '/' is not in VALID_TOKEN_RE's char class
            env = {**_isolated_env_for_parity(tmpdir), env_var: "valid-part/also-valid-part"}

            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            # If both implementations consider '/' invalid, both should return [].
            # If Rust "helpfully" splits on '/', it will return the two halves.
            assert py_list == rs_list, (
                f"Divergence on slash handling:\n"
                f"  Python (rejects '/' wholesale): {py_list}\n"
                f"  Rust (splits on '/'):           {rs_list}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize(
        "env_var,prefix,py_func",
        [
            ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()"),
            ("ANACONDA_ANON_USAGE_MACHINE_TOKEN", "m", "machine_tokens()"),
            ("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", "i", "installer_tokens()"),
        ],
    )
    def test_invalid_token_discarded(self, env_var, prefix, py_func):
        """Tokens exceeding 36 chars should be discarded by both."""
        tmpdir = _isolated_home()
        try:
            invalid_token = "x" * 37
            env = {**_isolated_env_for_parity(tmpdir), env_var: invalid_token}

            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert invalid_token not in py_list, f"Python accepted invalid: {py_list}"
            assert invalid_token not in rs_list, f"Rust accepted invalid: {rs_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize(
        "env_var,prefix,py_func",
        [
            ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()"),
            ("ANACONDA_ANON_USAGE_MACHINE_TOKEN", "m", "machine_tokens()"),
            ("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", "i", "installer_tokens()"),
        ],
    )
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_file_based_tokens(self, env_var, prefix, py_func):
        """Tokens in config directory files should be read by both."""
        fname_map = {
            "ANACONDA_ANON_USAGE_ORG_TOKEN": "org_token",
            "ANACONDA_ANON_USAGE_MACHINE_TOKEN": "machine_token",
            "ANACONDA_ANON_USAGE_INSTALLER_TOKEN": "installer_token",
        }
        fname = fname_map[env_var]

        if sys.platform == "win32":
            real_home = Path.home()
            conda_dir = real_home / ".conda"
            conda_dir.mkdir(exist_ok=True)
            token_file = conda_dir / fname
            env = None
        else:
            tmpdir = _isolated_home()
            token_file = Path(tmpdir) / ".conda" / fname
            env = _isolated_env_for_parity(tmpdir)

        token_file.write_text("file-based-token-99\n")
        try:
            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert (
                "file-based-token-99" in py_list
            ), f"Python missed file token: {py_list}"
            assert (
                "file-based-token-99" in rs_list
            ), f"Rust missed file token: {rs_list}"
        finally:
            token_file.unlink(missing_ok=True)
            if sys.platform != "win32":
                shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize(
        "env_var,prefix,py_func",
        [
            ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()"),
            ("ANACONDA_ANON_USAGE_MACHINE_TOKEN", "m", "machine_tokens()"),
            ("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", "i", "installer_tokens()"),
        ],
    )
    def test_env_plus_file_deduplicates(self, env_var, prefix, py_func):
        """Same token in env var and file should appear only once."""
        tmpdir = _isolated_home()
        try:
            fname_map = {
                "ANACONDA_ANON_USAGE_ORG_TOKEN": "org_token",
                "ANACONDA_ANON_USAGE_MACHINE_TOKEN": "machine_token",
                "ANACONDA_ANON_USAGE_INSTALLER_TOKEN": "installer_token",
            }
            fname = fname_map[env_var]
            token_file = Path(tmpdir) / ".conda" / fname
            token_file.write_text("dedup-test-token\n")

            env = {**_isolated_env_for_parity(tmpdir), env_var: "dedup-test-token"}

            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert (
                py_list.count("dedup-test-token") == 1
            ), f"Python duplicated: {py_list}"
            assert rs_list.count("dedup-test-token") == 1, f"Rust duplicated: {rs_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestFullTokenStringParity:
    """End-to-end: compare deterministic tokens between implementations."""

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_same_deterministic_tokens(self):
        """For file-backed tokens, Rust and Python should agree.

        Compares e/, o/, m/, i/ tokens. Skips c/ (node-tying) and s/ (random).
        Uses an isolated HOME so system tokens only come from controlled sources.

        Note: Python's conda-based SEARCH_PATH may include additional directories
        (e.g., sys.prefix) that the Rust crate does not compute. We therefore
        verify that Rust tokens are a subset of Python tokens and that any
        explicitly placed test tokens appear in both.
        """
        tmpdir = _isolated_home()
        try:
            env = _isolated_env_for_parity(tmpdir)

            # Set up a known org token so we have something to compare
            conda_dir = Path(tmpdir) / ".conda"
            (conda_dir / "org_token").write_text("parity-org-token\n")

            py_ua = _python_token_fresh("token_string()", env_override=env)
            rs_ua = _run_rust_tokens(env_override=env)

            py_tokens = _parse_tokens(py_ua)
            rs_tokens = _parse_tokens(rs_ua)

            # The controlled org token must appear in both
            assert "parity-org-token" in py_tokens.get(
                "o", []
            ), f"Python missing controlled org token: {py_tokens.get('o')}"
            assert "parity-org-token" in rs_tokens.get(
                "o", []
            ), f"Rust missing controlled org token: {rs_tokens.get('o')}"

            # Rust tokens should be a subset of Python tokens.
            # Python may have extra tokens from conda's sys.prefix search paths
            # that the standalone Rust crate does not compute.
            for prefix in ("e", "o", "m", "i"):
                py_set = set(py_tokens.get(prefix, []))
                rs_set = set(rs_tokens.get(prefix, []))
                extra = rs_set - py_set
                assert not extra, (
                    f"Rust has {prefix}/ tokens not in Python: {extra}\n"
                    f"  Python: {sorted(py_set)}\n"
                    f"  Rust:   {sorted(rs_set)}\n"
                    f"Python: {py_ua}\n"
                    f"Rust:   {rs_ua}"
                )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
