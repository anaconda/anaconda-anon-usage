# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import base64
import json
import re
import sys
import uuid
from collections import namedtuple
from os import environ
from os.path import expanduser, isdir, isfile, join

from . import __version__
from .utils import _debug, _random_token, _read_file, _saved_token, cached

Tokens = namedtuple(
    "Tokens",
    (
        "version",
        "client",
        "session",
        "environment",
        "anaconda_cloud",
        "organization",
        "machine",
    ),
)
CONFIG_DIR = expanduser("~/.conda")
ANACONDA_DIR = expanduser("~/.anaconda")
ORG_TOKEN_NAME = "org_token"
MACHINE_TOKEN_NAME = "machine_token"

# System tokens may consist of only letters, numbers,
# underscores, and dashes, with no more than 36 characters.
VALID_TOKEN_RE = r"^(?:[A-Za-z0-9]|_|-){1,36}$"


@cached
def version_token():
    """
    Returns the version token, which is just the
    version string itself.
    """
    return __version__


@cached
def _search_path():
    """
    Returns the search path for system tokens.
    """
    try:
        # Do not import SEARCH_PATH directly since we need to
        # temporarily patch it for testing
        from conda.base import constants as c_constants

        search_path = c_constants.SEARCH_PATH
    except ImportError:
        # Because this module was designed to be used even in
        # environments that do not include conda, we need a
        # fallback in case conda.base.constants.SEARCH_PATH
        # is not available. This is a pruned version of the
        # constructed value of this path as of 2024-12-13.
        _debug("conda not installed in this environment")
        if sys.platform == "win32":
            search_path = ("C:/ProgramData/conda/.condarc",)
        else:
            search_path = ("/etc/conda/.condarc", "/var/lib/conda/.condarc")
        search_path += (
            "$XDG_CONFIG_HOME/conda/.condarc",
            "~/.config/conda/.condarc",
            "~/.conda/.condarc",
            "~/.condarc",
            "$CONDARC",
        )
    result = []
    home = expanduser("~")
    for path in search_path:
        # Only consider directories where
        # .condarc could also be found
        if not path.endswith("/.condarc"):
            continue
        parts = path.split("/")[:-1]
        if parts[0] == "~":
            parts[0] = home
        elif parts[0].startswith("$"):
            parts[0] = environ.get(parts[0][1:])
            if not parts[0]:
                continue
        path = "/".join(parts)
        if isdir(path) and path != home:
            result.append(path)
    return result


def _system_tokens(fname, what):
    """
    Returns an organization or machine token installed somewhere
    in the conda path. Unlike most tokens, these will typically
    be installed by system administrators, often by mobile device
    management software. There can also be multiple tokens present
    along the path, in which case we combine them
    """
    tokens = []
    env_name = "ANACONDA_ANON_USAGE_" + fname.upper()
    t_token = environ.get(env_name)
    if t_token:
        _debug("Found %s token in environment: %s", what, t_token)
        tokens.append(t_token)
    for path in _search_path():
        fpath = join(path, fname)
        if isfile(fpath):
            t_token = _read_file(fpath, what + " token", single_line=True)
            tokens.append(t_token)
    # Deduplicate while preserving order
    tokens = list(dict.fromkeys(t for t in tokens if t))
    if not tokens:
        _debug("No %s tokens found", what)
    # Make sure the tokens we omit have only valid characters, so any
    # server-side token parsing is not frustrated.
    valid = [t for t in tokens if re.match(VALID_TOKEN_RE, t)]
    if len(valid) < len(tokens):
        invalid = ", ".join(t for t in tokens if t not in valid)
        _debug("One or more invalid %s tokens discarded: %s", what, invalid)
    return valid


@cached
def organization_tokens():
    """
    Returns the list of organization tokens.
    """
    return _system_tokens(ORG_TOKEN_NAME, "organization")


@cached
def machine_tokens():
    """
    Returns the list of machine tokens.
    """
    return _system_tokens(MACHINE_TOKEN_NAME, "machine")


@cached
def client_token():
    """
    Returns the client token. If a token has not yet
    been generated, an attempt is made to do so. If
    that fails, an empty string is returned.
    """
    fpath = join(CONFIG_DIR, "aau_token")
    return _saved_token(fpath, "client", node_tie=True)


@cached
def session_token():
    """
    Returns the session token, generated randomly for each
    execution of the process.
    """
    return _random_token("session")


@cached
def environment_token(prefix=None):
    """
    Returns the environment token for the given prefix, or
    sys.prefix if one is not supplied. If a token has not
    yet been generated, an attempt is made to do so. If that
    fails, an empty string is returned.
    """
    if prefix is None:
        prefix = sys.prefix
    fpath = join(prefix, "etc", "aau_token")
    return _saved_token(fpath, "environment", prefix)


def _jwt_to_token(s):
    """Unpacks an Anaconda auth token and returns the encoded user ID for
    potential inclusion in the user agent, along with its expiration.

    The Anaconda API key takes the form of a standard OAuth2 access token,
    with the additional requirement that the "sub" field is a UUID string.
    This code perorms a basic set of integrity checks to confirm that this
    is the case. If the checks pass, the function returns an encoded form
    of "sub" as well as the "exp" value to enable sorting by expiration.
    If the checks fail, the function returns (None, 0).

    The signature is not fully validated as part of the check; only that it
    is a base64-encoded value. Validation is left to anaconda-auth.

    Returns:
      token: the token if valid; None otherwise
      exp: the expiration time
    """
    if not s:
        return None, 0
    try:
        # The JWT should have three parts separated by periods
        parts = s.split(".")
        assert len(parts) == 3 and all(parts), "3 parts expected"
        # Each part should be base64 encoded
        parts = list(map(lambda x: base64.urlsafe_b64decode(x + "==="), parts))
        # The header and payload should be json dictionaries
        parts = list(map(json.loads, parts[:2]))
        assert isinstance(parts[0], dict), "Invalid header"
        assert parts[0].get("typ") == "JWT", "Invalid header"
        assert isinstance(parts[1], dict), "Invalid payload"
        # The payload should have a positive integer expiration
        exp = parts[1].get("exp")
        assert isinstance(exp, int) and exp > 0, "Invalid expiration"
        # The subscriber should be a non-empty UUID string
        sub = parts[1].get("sub")
        assert sub, "Invalid subscriber"
        # This is an Anaconda requirement, not a JWT requirement
        sub = uuid.UUID(sub).bytes
        token = base64.urlsafe_b64encode(sub).decode("ascii").strip("=")
        return token, exp
    except Exception as exc:
        _debug("Unexpected %s parsing API key: %s", type(exc), exc)
        return None, 0


@cached
def anaconda_auth_token():
    """Retrieve Anaconda Cloud token from keyring.

    Examines all entries under 'Anaconda Cloud' in the keyring and
    selects the token with the latest expiration date. This handles
    migration from 'anaconda.cloud' to 'anaconda.com' entries.

    Returns:
        str: Base64-encoded token, or None if no valid token found.
    """
    env = environ.get("ANACONDA_AUTH_API_KEY")
    if env:
        _debug("ANACONDA_AUTH_API_KEY environment variable found")
        token, _ = _jwt_to_token(env)
        if token:
            _debug("Retrieved Anaconda token from environment: %s", token)
            return token
        _debug("Could not retrieve API key from environment")
    fpath = expanduser(join(ANACONDA_DIR, "keyring"))
    data = _read_file(fpath, "anaconda keyring")
    if not data:
        return
    try:
        data = json.loads(data)
    except Exception as exc:
        _debug("Unexpected JSON decoding error parsing keyring file: %s", exc)
        return
    if not data or not isinstance(data, dict):
        _debug("Empty keyring")
        return
    token, exp = None, 0
    for key, rec in (data.get("Anaconda Cloud") or {}).items():
        try:
            tdata = json.loads(base64.b64decode(rec))["api_key"]
        except Exception as exc:
            _debug("Unexpected error parsing keyring entry '%s': %s", key, exc)
        t_token, t_exp = _jwt_to_token(tdata)
        if t_exp > exp:
            token = t_token
            exp = t_exp
    if token:
        _debug("Retrieved Anaconda token from keyring: %s", token)
    else:
        _debug("No Anaconda keyring records found")
    return token


@cached
def all_tokens(prefix=None):
    """
    Returns the token set, in the form of a Tokens namedtuple.
    Fields: version, client, session, environment
    """
    return Tokens(
        version_token(),
        client_token(),
        session_token(),
        environment_token(prefix),
        anaconda_auth_token(),
        organization_tokens(),
        machine_tokens(),
    )


@cached
def token_string(prefix=None, enabled=True):
    """
    Returns the token set, formatted into the string that is
    appended to the conda user agent.
    """
    parts = ["aau/" + __version__]
    if enabled:
        values = all_tokens(prefix)
        if values.client:
            parts.append("c/" + values.client)
        if values.session:
            parts.append("s/" + values.session)
        if values.environment:
            parts.append("e/" + values.environment)
        if values.anaconda_cloud:
            parts.append("a/" + values.anaconda_cloud)
        # Organization and machine tokens can potentially be
        # multi-valued, and this is rendered in the user agent
        # string as multiple instances separated by spaces. This
        # was chosen to facilitate easier filtering & search
        if values.organization:
            parts.extend("o/" + t for t in values.organization)
        if values.machine:
            parts.extend("m/" + t for t in values.machine)
    else:
        _debug("anaconda_anon_usage disabled by config")
    result = " ".join(parts)
    _debug("Full aau token string: %s", result)
    return result


if __name__ == "__main__":
    if "--random" in sys.argv:
        print(_random_token())
    else:
        print(token_string())
