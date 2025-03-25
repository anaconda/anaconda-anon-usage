# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import base64
import json
import sys
import time
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
ORG_TOKEN_NAME = "org_token"
MACHINE_TOKEN_NAME = "machine_token"


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
    for path in _search_path():
        fpath = join(path, fname)
        if not isfile(fpath):
            continue
        t_tokens = _read_file(fpath, what + " token", single_line=True)
        if t_tokens:
            for token in t_tokens.split("/"):
                if token not in tokens:
                    tokens.append(token)
    if not tokens:
        _debug("No %s tokens found", what)
    return tokens


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
def anaconda_cloud_token():
    """
    Returns the token for the logged-in anaconda user, if present.
    """
    fpath = expanduser(join("~", ".anaconda", "keyring"))
    data = _read_file(fpath, "anaconda keyring")
    if not data:
        return
    try:
        data = json.loads(data)["Anaconda Cloud"]["anaconda.cloud"]
        data = json.loads(base64.b64decode(data))["api_key"]
        data = json.loads(base64.b64decode(data.split(".", 2)[1] + "==="))
        data["exp"] = int(data["exp"])
        data["sub"] = uuid.UUID(data["sub"]).bytes
    except Exception as exc:
        _debug("Unexpected error parsing keyring file: %s", exc)
        return
    if time.time() > data["exp"]:
        _debug("Anaconda Cloud token has expired")
        return
    token = base64.urlsafe_b64encode(data["sub"]).decode("ascii").strip("=")
    _debug("Retrieved Anaconda Cloud token: %s", token)
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
        anaconda_cloud_token(),
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
