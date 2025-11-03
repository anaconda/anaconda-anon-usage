# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import re
import sys
from collections import namedtuple
from os import environ
from os.path import expanduser, isdir, isfile, join

from . import __version__
from .api_key import get_api_key
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


@cached
def anaconda_auth_token():
    """Returns the base64-encoded uid corresponding to the logged
    in Anaconda Cloud user, if one is present.
    Returns:
        str: Base64-encoded token, or None if no valid token found.
    """
    _, token = get_api_key()
    if token:
        _debug("Retrieved Anaconda API key for UUID: %s", token)
    else:
        _debug("No Anaconda API key found")
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
