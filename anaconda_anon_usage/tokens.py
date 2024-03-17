# This module provides functions for reading and writing the
# anonymous token set. It has been designed to rely only on the
# Python standard library. In particular, hard dependencies on
# conda must be avoided so that this package can be used in
# child environments.

import os
import re
import sys
from collections import namedtuple
from os.path import expanduser, join

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


_token_value = None


@cached
def auth_string(url, enabled=True):
    """
    Returns the X-Auth header to send for the given URL. The purpose
    is to indicate to repo.anaconda.com that the user is a registered
    and logged-in member of anaconda.cloud. To that end, the auth
    string will be non-empty only if all of the following are true:
    - anaconda_anon_usage is enabled
    - the request url is http[s]://*.anaconda.com
    - the user has an installed token for anaconda.(cloud|org)
    Furthermore, the patch code will apply this header only if there
    is not an existing X-Auth header on the request.
    """
    global _token_value
    if not enabled:
        _debug("auth string disabled by config")
        return
    if "anaconda.com" not in url:
        _debug("auth string only sent to anaconda.com")
        return
    if not re.match(r"^https?://(?:[^/]*[.])?anaconda[.]com(?:/.*)?$", url):
        _debug("auth string only sent to anaconda.com")
        return
    if _token_value is not None:
        return _token_value
    candidates = [(4, "")]
    priorities = {"com": 1, "cloud": 2, "org": 3}
    from conda.gateways import anaconda_client as ac

    all_tokens = ac.read_binstar_tokens()
    debug_token = os.environ.get("ANACONDA_ANON_USAGE_DEBUG_TOKEN")
    if debug_token:
        all_tokens["https://repo.anaconda.com/"] = debug_token
    for t_url, t_val in all_tokens.items():
        match = re.match(
            r"^https?://(?:[^/]*[.])?anaconda[.](cloud|com|org)(?:/.*)?$", t_url
        )
        if match:
            candidates.append((priorities.get(match.groups()[0], 5), t_val))
    _token_value = min(candidates)[1]
    return _token_value
