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


# Env vars that must be passed through to subprocesses for them to function at all.
# On POSIX only PATH is really needed; Windows needs its own minimum set or Python
# and the Rust binary will fail to initialize.
_SUBPROCESS_ENV_ALLOWLIST = (
    "PATH",
    # Windows essentials — subprocess/Python break without these
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "TEMP",
    "TMP",
    "PATHEXT",
    "COMSPEC",
    "PROCESSOR_ARCHITECTURE",
    # macOS/Linux Rust binaries dlopen/link against system libs reachable via these
    "DYLD_LIBRARY_PATH",
    "LD_LIBRARY_PATH",
)


def _subprocess_env(env_override=None):
    """Build a subprocess env from a small allowlist, then apply overrides.

    Nothing from the caller's environment leaks in unless it's on the allowlist.
    Callers use env_override to add exactly what each test needs.
    """
    env = {}
    for key in _SUBPROCESS_ENV_ALLOWLIST:
        val = os.environ.get(key)
        if val is not None:
            env[key] = val
    if env_override:
        env.update(env_override)
    return env


def _run_rust(args, env_override=None):
    """Run the Rust binary with the given arguments."""
    result = subprocess.run(
        [RUST_BIN] + args,
        capture_output=True,
        text=True,
        env=_subprocess_env(env_override),
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
    code = f"""
import os, sys
from anaconda_anon_usage import tokens
result = tokens.{func_name}
if isinstance(result, list):
    print('\\n'.join(result))
elif result is not None:
    print(result)
"""
    # Python needs to locate the anaconda_anon_usage package — inherit PYTHONPATH
    # and the currently-active venv/prefix so imports resolve the same interpreter.
    py_env = _subprocess_env(env_override)
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        if key in os.environ and key not in py_env:
            py_env[key] = os.environ[key]
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=py_env,
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

    With the subprocess env built from a strict allowlist (see _subprocess_env),
    unknown env vars can't leak in. This helper only has to set the positive
    values each implementation needs:
    - $HOME (platform-aware, via _home_env)
    - ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT — overrides /etc/conda, /var/lib/conda,
      C:/ProgramData/conda in both Python and Rust implementations
    """
    tmpdir = str(tmpdir)
    env = _home_env(tmpdir)
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
            env = {
                **_isolated_env_for_parity(tmpdir),
                env_var: "token-alpha/token-beta",
            }

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
    def test_env_var_with_invalid_char_rejected_identically(
        self, env_var, prefix, py_func
    ):
        """A token with invalid chars should be rejected by both implementations
        in the same way — not discarded by one and salvaged-by-splitting by the other.
        """
        tmpdir = _isolated_home()
        try:
            # '/' is not in VALID_TOKEN_RE's char class
            env = {
                **_isolated_env_for_parity(tmpdir),
                env_var: "valid-part/also-valid-part",
            }

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


class TestBugFixParity:
    """Regression tests for specific Python/Rust parity bugs.

    Each test targets a bug that existed before this test class was added.
    Before the corresponding fix, the test would fail; after, it passes on
    both implementations.
    """

    # Bug 1 — Rust previously fell back to now=0 if SystemTime::now() failed,
    # making any JWT with positive exp appear valid. The fix rejects the JWT.
    # Cannot force SystemTime failure from a parity test, so we exercise the
    # adjacent contract that both sides agree on: an expired JWT is rejected.
    def test_expired_jwt_rejected_by_both(self):
        """An expired JWT must produce no a/ token in either implementation."""
        import datetime as dt
        import json as _json

        def _b64url(obj):
            raw = _json.dumps(obj).encode("ascii")
            return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

        exp = int(dt.datetime.now(tz=dt.timezone.utc).timestamp()) - 3600
        header = _b64url({"alg": "RS256", "typ": "JWT"})
        payload = _b64url({"exp": exp, "sub": str(uuid.uuid4())})
        signature = _b64url({"fake": "sig"})
        expired_jwt = f"{header}.{payload}.{signature}"

        from anaconda_anon_usage.tokens import _jwt_to_token

        assert _jwt_to_token(expired_jwt) is None, "Python accepted expired JWT"

        rs_tokens = _parse_tokens(_run_rust_tokens(extra_args=["--jwt", expired_jwt]))
        assert "a" not in rs_tokens, f"Rust accepted expired JWT: {rs_tokens.get('a')}"

    # Bug 2 — single_line file reads must strip per-line, not globally. A file
    # with leading whitespace on the first line (e.g. "  token\n# comment") was
    # previously returned as "  token" and then rejected by VALID_TOKEN_RE.
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
    def test_file_leading_whitespace_stripped_per_line(self, env_var, prefix, py_func):
        """Token file with whitespace around the first line must strip per-line.

        FIXED in:
          - anaconda_anon_usage/utils.py :: _read_file (single_line branch)
          - rust/src/utils.rs :: read_file (single_line branch)
        """
        fname_map = {
            "ANACONDA_ANON_USAGE_ORG_TOKEN": "org_token",
            "ANACONDA_ANON_USAGE_MACHINE_TOKEN": "machine_token",
            "ANACONDA_ANON_USAGE_INSTALLER_TOKEN": "installer_token",
        }
        fname = fname_map[env_var]
        tmpdir = _isolated_home()
        try:
            token_file = Path(tmpdir) / ".conda" / fname
            # Leading spaces on the first line + trailing comment. Pre-fix,
            # Python would return "  token-with-pad" (fails VALID_TOKEN_RE);
            # Rust would return "token-with-pad" (passes). Post-fix, both
            # return "token-with-pad" and accept it.
            token_file.write_text("  token-with-pad  \n# comment\n")

            env = _isolated_env_for_parity(tmpdir)
            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert py_list == rs_list, (
                f"Per-line stripping divergence:\n"
                f"  Python: {py_list}\n"
                f"  Rust:   {rs_list}"
            )
            assert "token-with-pad" in py_list
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # Bug 3 — Python previously appended literal "~/.conda" when $HOME was
    # unset, turning a missing home directory into an accidental cwd-relative
    # read. The fix skips home entries when expanduser("~") returns "~".
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="Windows expanduser uses USERPROFILE; different failure mode",
    )
    def test_python_skips_home_paths_when_home_unresolvable(self):
        """With HOME unset, Python _search_path must not include '~/...' entries.

        FIXED in:
          - anaconda_anon_usage/tokens.py :: _search_path
        """
        code = (
            "import sys\n"
            "from anaconda_anon_usage.tokens import _search_path\n"
            "from anaconda_anon_usage.utils import _cache_clear\n"
            "_cache_clear()\n"
            "paths = _search_path()\n"
            "bad = [p for p in paths if p.startswith('~')]\n"
            "sys.exit(1 if bad else 0)\n"
        )
        # Strip HOME from subprocess env. _subprocess_env already excludes it
        # unless we add it; don't add it.
        env = {}
        for key in _SUBPROCESS_ENV_ALLOWLIST:
            val = os.environ.get(key)
            if val is not None:
                env[key] = val
            if "HOME" in env:
                del env["HOME"]
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            if key in os.environ:
                env[key] = os.environ[key]
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            "Python _search_path included a literal '~' entry when HOME was unset.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )

    # Bug 4 — Rust previously trimmed env var values before validating them,
    # so " valid-token " was accepted by Rust but rejected by Python. The fix
    # passes env var values through raw.
    @pytest.mark.parametrize(
        "env_var,prefix,py_func",
        [
            ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()"),
            ("ANACONDA_ANON_USAGE_MACHINE_TOKEN", "m", "machine_tokens()"),
            ("ANACONDA_ANON_USAGE_INSTALLER_TOKEN", "i", "installer_tokens()"),
        ],
    )
    def test_env_var_surrounding_whitespace_rejected_identically(
        self, env_var, prefix, py_func
    ):
        """Env var with whitespace must be rejected by both (not trimmed by one).

        FIXED in:
          - rust/src/tokens.rs :: parse_token_value and env var handler
            (no longer trim env var values before validation)
        """
        tmpdir = _isolated_home()
        try:
            env = {
                **_isolated_env_for_parity(tmpdir),
                env_var: "  whitespace-padded-token  ",
            }

            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert py_list == rs_list, (
                f"Divergence on whitespace-padded env token:\n"
                f"  Python: {py_list}\n"
                f"  Rust:   {rs_list}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    # Bug 9 — Python previously resolved join("", "etc", "aau_token") to the
    # relative path "etc/aau_token" when prefix was the empty string. The fix
    # skips when prefix is empty, matching Rust.
    def test_python_skips_environment_token_when_prefix_empty(self):
        """environment_token('') must return '' (not read a relative path).

        FIXED in:
          - anaconda_anon_usage/tokens.py :: environment_token
        """
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from anaconda_anon_usage.tokens import environment_token;"
                    "r = environment_token(''); print('EMPTY' if r == '' else r)"
                ),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Python errored: {result.stderr}"
        assert result.stdout.strip() == "EMPTY", (
            f"Python environment_token('') did not return empty string: "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


class TestFileFormatEdgeCases:
    """File-format edge cases for _read_file / read_file on both sides."""

    # Token file param set shared by several tests below
    _params = [
        ("ANACONDA_ANON_USAGE_ORG_TOKEN", "o", "organization_tokens()", "org_token"),
        (
            "ANACONDA_ANON_USAGE_MACHINE_TOKEN",
            "m",
            "machine_tokens()",
            "machine_token",
        ),
        (
            "ANACONDA_ANON_USAGE_INSTALLER_TOKEN",
            "i",
            "installer_tokens()",
            "installer_token",
        ),
    ]

    @pytest.mark.parametrize("env_var,prefix,py_func,fname", _params)
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_utf8_bom_on_first_line(self, env_var, prefix, py_func, fname):
        """A UTF-8 BOM on the first line must be handled identically by both sides.

        Neither side strips the BOM. The token "\\ufefftoken-bom" contains a
        character outside VALID_TOKEN_RE, so both sides should reject it.
        What we verify is that both sides agree on rejection — i.e. neither
        side silently strips the BOM.
        """
        tmpdir = _isolated_home()
        try:
            token_file = Path(tmpdir) / ".conda" / fname
            token_file.write_bytes(b"\xef\xbb\xbfbom-test-token\n")

            env = _isolated_env_for_parity(tmpdir)
            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert (
                py_list == rs_list
            ), f"BOM handling divergence:\n  Python: {py_list}\n  Rust:   {rs_list}"
            assert (
                "bom-test-token" not in py_list
            ), "BOM was silently stripped by Python"
            assert "bom-test-token" not in rs_list, "BOM was silently stripped by Rust"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize("env_var,prefix,py_func,fname", _params)
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_crlf_line_endings(self, env_var, prefix, py_func, fname):
        """CRLF line endings must not leave \\r tacked onto the extracted token."""
        tmpdir = _isolated_home()
        try:
            token_file = Path(tmpdir) / ".conda" / fname
            token_file.write_bytes(b"crlf-token\r\n# trailing comment\r\n")

            env = _isolated_env_for_parity(tmpdir)
            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert (
                py_list == rs_list
            ), f"CRLF handling divergence:\n  Python: {py_list}\n  Rust:   {rs_list}"
            assert "crlf-token" in py_list, f"Python mangled CRLF token: {py_list}"
            assert "crlf-token" in rs_list, f"Rust mangled CRLF token: {rs_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize("env_var,prefix,py_func,fname", _params)
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="symlinks require admin on Windows; also HOME isolation doesn't work",
    )
    def test_symlinked_token_file(self, env_var, prefix, py_func, fname):
        """A symlinked token file must be followed and read on both sides."""
        tmpdir = _isolated_home()
        try:
            target = Path(tmpdir) / "real_token_file"
            target.write_text("symlink-target-token\n")
            link = Path(tmpdir) / ".conda" / fname
            link.symlink_to(target)

            env = _isolated_env_for_parity(tmpdir)
            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert "symlink-target-token" in py_list, f"Python: {py_list}"
            assert "symlink-target-token" in rs_list, f"Rust: {rs_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize("env_var,prefix,py_func,fname", _params)
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_comment_only_first_line_rejected(self, env_var, prefix, py_func, fname):
        """A file whose first non-blank line is a comment must yield no token.

        Both sides extract only the first non-blank line; a comment starting
        with '#' contains a character outside VALID_TOKEN_RE and must be
        rejected. Critically: neither side should fall through to a later
        line.
        """
        tmpdir = _isolated_home()
        try:
            token_file = Path(tmpdir) / ".conda" / fname
            # Comment first, then what looks like a valid token.
            # Both sides should extract '# comment here' and reject it — the
            # second line must not leak through.
            token_file.write_text("# comment here\nshould-not-appear\n")

            env = _isolated_env_for_parity(tmpdir)
            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert py_list == rs_list, (
                f"Comment-only divergence:\n"
                f"  Python: {py_list}\n  Rust:   {rs_list}"
            )
            assert (
                "should-not-appear" not in py_list
            ), f"Python leaked line 2: {py_list}"
            assert "should-not-appear" not in rs_list, f"Rust leaked line 2: {rs_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.parametrize("env_var,prefix,py_func,fname", _params)
    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_valid_token_with_trailing_comments(self, env_var, prefix, py_func, fname):
        """A valid token on line 1 with trailing comments must be extracted."""
        tmpdir = _isolated_home()
        try:
            token_file = Path(tmpdir) / ".conda" / fname
            token_file.write_text("valid-first-line\n# a comment\n# another comment\n")

            env = _isolated_env_for_parity(tmpdir)
            py_tokens = _python_token_fresh(py_func, env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get(prefix, [])

            assert "valid-first-line" in py_list, f"Python: {py_list}"
            assert "valid-first-line" in rs_list, f"Rust: {rs_list}"
            assert py_list == rs_list, (
                f"Mixed content divergence:\n"
                f"  Python: {py_list}\n  Rust:   {rs_list}"
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestTokenOrdering:
    """Multi-token ordering across search paths and dotfile variants."""

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_multi_directory_token_ordering(self):
        """When the same token type appears in system-root and home dirs,
        both sides must emit the tokens in the same order.

        Python iterates _search_path() in order: system root, then CONDA_ROOT,
        then XDG_CONFIG_HOME/conda, then ~/.config/conda, then ~/.conda.
        Rust mirrors this. At each path, both sides try the plain filename
        first, then the dotfile variant.
        """
        tmpdir = _isolated_home()
        try:
            env = _isolated_env_for_parity(tmpdir)
            sys_root = Path(env["ANACONDA_ANON_USAGE_TEST_SYSTEM_ROOT"])

            # Token in two locations: system root and home.
            # Both should appear, system-root first.
            (sys_root / "org_token").write_text("sys-root-first\n")
            (Path(tmpdir) / ".conda" / "org_token").write_text("home-second\n")

            py_tokens = _python_token_fresh("organization_tokens()", env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get("o", [])

            assert py_list == rs_list, (
                f"Multi-directory ordering divergence:\n"
                f"  Python: {py_list}\n  Rust:   {rs_list}"
            )
            # Both tokens should appear; system root should come first
            assert "sys-root-first" in py_list
            assert "home-second" in py_list
            assert py_list.index("sys-root-first") < py_list.index(
                "home-second"
            ), f"Expected system-root token before home token: {py_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="dirs crate on Windows ignores USERPROFILE; cannot isolate HOME",
    )
    def test_plain_before_dotfile_within_directory(self):
        """Within one directory, the plain filename comes before the dotfile."""
        tmpdir = _isolated_home()
        try:
            env = _isolated_env_for_parity(tmpdir)
            conda_dir = Path(tmpdir) / ".conda"
            (conda_dir / "org_token").write_text("plain-variant\n")
            (conda_dir / ".org_token").write_text("dot-variant\n")

            py_tokens = _python_token_fresh("organization_tokens()", env_override=env)
            py_list = [t for t in py_tokens.split("\n") if t]

            rs_tokens = _parse_tokens(_run_rust_tokens(env_override=env))
            rs_list = rs_tokens.get("o", [])

            assert py_list == rs_list, (
                f"Plain/dotfile ordering divergence:\n"
                f"  Python: {py_list}\n  Rust:   {rs_list}"
            )
            assert "plain-variant" in py_list
            assert "dot-variant" in py_list
            assert py_list.index("plain-variant") < py_list.index(
                "dot-variant"
            ), f"Expected plain filename before dotfile: {py_list}"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestCaching:
    """Within a single process, repeated calls return the same token."""

    def test_client_token_stable_within_process(self):
        """Calling client_token() twice in one Python process returns the same
        value, and doing the same in Rust (two tokens from one CLI invocation)
        also matches the cached value.
        """
        tmpdir = _isolated_home()
        try:
            env = _home_env(tmpdir)
            code = (
                "from anaconda_anon_usage.tokens import client_token;"
                "print(client_token()); print(client_token())"
            )
            py_env = _subprocess_env(env)
            for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
                if key in os.environ:
                    py_env[key] = os.environ[key]
            result = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                env=py_env,
            )
            assert result.returncode == 0, f"Python failed: {result.stderr}"
            lines = [line for line in result.stdout.strip().splitlines() if line]
            assert len(lines) == 2, f"Expected 2 lines, got: {lines}"
            assert lines[0] == lines[1], f"Python client_token not cached: {lines}"

            # Rust: run the binary twice in the same temp home; both runs should
            # produce the same client token (file-backed, not regenerated).
            rs_first = _parse_tokens(_run_rust_tokens(env_override=env)).get(
                "c", [None]
            )[0]
            rs_second = _parse_tokens(_run_rust_tokens(env_override=env)).get(
                "c", [None]
            )[0]
            assert (
                rs_first == rs_second
            ), f"Rust client token not stable across runs: {rs_first} vs {rs_second}"
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
