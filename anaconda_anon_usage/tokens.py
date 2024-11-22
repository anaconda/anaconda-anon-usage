# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import sys
from collections import namedtuple
from os.path import expanduser, abspath, join, exists, dirname
from conda.base import constants as c_constants

from . import __version__
from .utils import _debug, _random_token, _saved_token, cached

Tokens = namedtuple("Tokens", ("version", "client", "session", "environment"))
CONFIG_DIR = expanduser("~/.conda")


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
    The system token is a token installed into a read-only system
    location, presumably by MDM software. If present, it is used
    as an enforced prefix to the client token.
    """
    # Do not import SEARCH_PATH directly since we need to
    # temporarily patch it for testing
    for path in c_constants.SEARCH_PATH:
        # Terminate the search at the first encounter
        # with a non-system directory, to ensure that
        # we use only system directories.
        if path.startswith('~'):
            break
        # Do not use the directories that involve
        # environment variables, or .d/ directories
        if path.startswith('$') or path.endswith('/'):
            continue
        path = join(dirname(path), "aau_token")
        if exists(path):
            try:
                _debug("Reading system token: %s", path)
                with open(path, "r") as fp:
                    return fp.read()
            except:
                _debug("Unabled to read system token")
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
    return _saved_token(fpath, "client", seed=system_token())


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
        version_token(), client_token(), session_token(), environment_token(prefix)
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
    else:
        _debug("anaconda_anon_usage disabled by config")
    result = " ".join(parts)
    _debug("Full client token: %s", result)
    return result
