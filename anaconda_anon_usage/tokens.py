# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import functools
import sys
from collections import namedtuple
from os.path import expanduser, join

from . import __version__
from .utils import _debug, _random_token, _saved_token

Tokens = namedtuple("Tokens", ("version", "client", "session", "environment"))


def version_token():
    """
    Returns the version token, which is just the
    version string itself.
    """
    return __version__


@functools.lru_cache(maxsize=None)
def client_token():
    """
    Returns the client token. If a token has not yet
    been generated, an attempt is made to do so. If
    that fails, an empty string is returned.
    """
    fpath = join(expanduser("~/.conda"), "aau_token")
    return _saved_token(fpath, "client")


@functools.lru_cache(maxsize=None)
def session_token():
    """
    Returns the session token, generated randomly for each
    execution of the process.
    """
    return _random_token()


@functools.lru_cache(maxsize=None)
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
    return _saved_token(fpath, "environment")


@functools.lru_cache(maxsize=None)
def all_tokens(prefix=None):
    """
    Returns the token set, in the form of a Tokens namedtuple.
    Fields: version, client, session, environment
    """
    return Tokens(
        version_token(), client_token(), session_token(), environment_token(prefix)
    )


@functools.lru_cache(maxsize=None)
def token_string(prefix=None):
    """
    Returns the token set, formatted into the string that is
    appended to the conda user agent.
    """
    values = all_tokens(prefix)
    parts = ["aau/" + values.version]
    if values.client:
        parts.append("c/" + values.client)
    parts.append("s/" + values.session)
    if values.environment:
        parts.append("e/" + values.environment)
    result = " ".join(parts)
    _debug("Full client token: %s", result)
    return result
