# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import sys
from collections import namedtuple
from os import environ
from os.path import expanduser, isfile, join

from conda.base import constants as c_constants

from . import __version__
from .utils import _debug, _random_token, _saved_token, cached

Tokens = namedtuple("Tokens", ("version", "client", "session", "environment", "system"))
CONFIG_DIR = expanduser("~/.conda")
ORG_TOKEN_NAME = "org_token"


@cached
def version_token():
    """
    Returns the version token, which is just the
    version string itself.
    """
    return __version__


@cached
def system_token():
    """
    Returns the system/organization token. Unlike the other
    tokens, it is desirable for this token to be stored in
    a read-only/system location, presumably installed
    The system/organization token can be stored anywhere
    in the standard conda search path. Ideally, an MDM system
    would place it in a read-only system location.
    """
    # Do not import SEARCH_PATH directly since we need to
    # temporarily patch it for testing
    for path in c_constants.SEARCH_PATH:
        # Only consider directories where
        # .condarc could also be found
        if not path.endswith("/.condarc"):
            continue
        parts = path.split("/")
        if parts[0].startswith("$"):
            parts[0] = environ.get(parts[0][1:])
            if not parts[0]:
                continue
        parts[-1] = ORG_TOKEN_NAME
        path = "/".join(parts)
        if isfile(path):
            try:
                _debug("Reading system token: %s", path)
                with open(path) as fp:
                    return fp.read().strip()
            except Exception:
                _debug("Unable to read system token")
                return
    _debug("No system token found")


@cached
def client_token():
    """
    Returns the client token. If a token has not yet
    been generated, an attempt is made to do so. If
    that fails, an empty string is returned.
    """
    fpath = join(CONFIG_DIR, "aau_token")
    return _saved_token(fpath, "client")


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
        system_token(),
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
        if values.system:
            parts.append("o/" + values.system)
    else:
        _debug("anaconda_anon_usage disabled by config")
    result = " ".join(parts)
    _debug("Full client token: %s", result)
    return result


if __name__ == "__main__":
    print(token_string())
