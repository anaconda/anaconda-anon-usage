# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import base64
import functools
import os
import sys
from collections import namedtuple
from os.path import dirname, exists, expanduser, join
from uuid import uuid4

from . import __version__

DEBUG = bool(os.environ.get("ANACONDA_ANON_USAGE_DEBUG"))
Tokens = namedtuple("Tokens", ("version", "client", "session", "environment"))


def _debug(s, *args, error=False):
    if error or DEBUG:
        print(s % args, file=sys.stderr)


def _random_token():
    return base64.urlsafe_b64encode(uuid4().bytes).strip(b"=").decode("ascii")


def _saved_token(fpath, what):
    """
    Implements the saved token functionality. If the specified
    file exists, and contains a token with the right format,
    return it. Otherwise, generate a new one and save it in
    this location. If that fails, return an empty string.
    """
    client_token = ""
    _debug("%s token path: %s", what.capitalize(), fpath)
    if exists(fpath):
        try:
            # Use just the first line of the file, if it exists
            client_token = "".join(open(fpath).read().splitlines()[:1])
            _debug("Retrieved %s token: %s", what, client_token)
        except Exception as exc:
            _debug("Unexpected error reading: %s\n  %s", fpath, exc, error=True)
    if len(client_token) < 22:
        if len(client_token) > 0:
            _debug("Generating longer token")
        client_token = _random_token()
        try:
            os.makedirs(dirname(fpath), exist_ok=True)
            with open(fpath, "w") as fp:
                fp.write(client_token)
            _debug("Generated new token: %s", client_token)
            _debug("%s token saved: %s", what.capitalize(), fpath)
        except Exception as exc:
            _debug("Unexpected error writing: %s\n  %s", fpath, exc, error=True)
            client_token = ""
    return client_token


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
