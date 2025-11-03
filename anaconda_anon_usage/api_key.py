# This module contains functions to retrieve a valid Anaconda
# API key from any of the locations where it might reside, as
# defined by the conventions of the anaconda_auth module. We
# do first try to use anaconda_auth itself, but at least for
# now we attempt to reproduce the loading behavior of that
# module independently, in case the module is not present,
# to more easily support CI/CD or Docker scenarios.

import base64
import datetime as dt
import json
import os
import uuid
from os.path import expanduser, expandvars, isdir, join

from .utils import _debug, cached


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
        return None, None
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
        now = dt.datetime.now(tz=dt.timezone.utc).timestamp()
        if exp < now:
            _debug("API key expired %ds ago", int(now - exp))
            return None, None
        # The subscriber should be a non-empty UUID string
        sub = parts[1].get("sub")
        assert sub, "Invalid subscriber"
        # This is an Anaconda requirement, not a JWT requirement
        sub = uuid.UUID(sub).bytes
        token = base64.urlsafe_b64encode(sub).decode("ascii").strip("=")
        return s, token
    except Exception as exc:
        _debug("Unexpected %s parsing API key: %s", type(exc), exc)
        return None, None


def _keyring_to_api_key(keyring, domain=None):
    if keyring is None:
        return None
    if keyring and isinstance(keyring, str):
        try:
            keyring = json.loads(keyring)
        except Exception as exc:
            _debug("Unexpected JSON decoding error parsing keyring: %s", exc)
            return ""
    if not isinstance(keyring, dict):
        _debug("Unexpected keyring content:% s", keyring)
        return ""
    keyring_name = "Anaconda Cloud"
    all_domains = keyring.get(keyring_name)
    if not domain:
        domain = _domain()
    if not domain:
        for domain in ("anaconda.com", "anaconda.cloud"):
            if domain in all_domains:
                break
        else:
            domain = "anaconda.com"
    rec = all_domains.get(domain)
    if not rec:
        _debug("API key not found for domain: %s", domain)
        return ""
    try:
        _debug("API key found for domain: %s", domain)
        return json.loads(base64.b64decode(rec + "==="))["api_key"]
    except Exception as exc:
        _debug("Unexpected error decoding api_key: %s", exc)
    return ""


def _module():
    try:
        from anaconda_auth.config import AnacondaAuthSitesConfig
        from anaconda_auth.token import TokenInfo, TokenNotFoundError

        _debug("Module anaconda_auth loaded")
    except ImportError:
        _debug("Module anaconda_auth not loaded")
        return
    try:
        config = AnacondaAuthSitesConfig.load_site()
        if config.api_key:
            _debug("Configured anaconda_auth api key found")
            return config.api_key
        try:
            tinfo = TokenInfo.load(domain=config.domain)
            if tinfo.api_key:
                _debug("API key found for domain: %s", config.domain)
                return tinfo.api_key
        except TokenNotFoundError:
            _debug("No API key found for domain: %s", config.domain)
    except Exception as exc:
        _debug("Unexpected error retrieving token using anaconda_auth: %s", exc)
    return ""


def _env(key, what):
    key = key.upper()
    result = os.environ.get(key)
    if result is None:
        key = key.lower()
        result = os.environ.get(key)
    if result is not None:
        _debug("Found environment variable: %s", key)
        _debug("Selected %s: %s", what, result)
    return result


def _file(fpath, what):
    try:
        with open(fpath) as fp:
            data = fp.read().rstrip()
        _debug("Successfully read %s: %s", what, fpath)
    except FileNotFoundError:
        return None
    except Exception as exc:
        _debug("Unexpected decoding error reading %s file %s: %s", what, fpath, exc)
        data = ""
    return data


@cached
def _secrets_dir():
    path = os.getenv("ANACONDA_SECRETS_DIR")
    path = expandvars(expanduser(path)) if path else "/run/secrets"
    return path if isdir(path) else None


def _secret(key, what):
    path = _secrets_dir()
    if not path:
        return
    what += " secret"
    result = _file(join(path, key), what)
    if not result:
        key = key.lower()
        result = _file(join(path, key), what)
    if result:
        _debug("Selected %s: %s", what, result)
    return result


def _domain():
    key, what = "ANACONDA_AUTH_DOMAIN", "Anaconda domain"
    return _env(key, what) or _secret(key, what)


def _api_key():
    key, what = "ANACONDA_AUTH_API_KEY", "API key"
    return _env(key, what) or _secret(key, what)


def _keyring():
    key, what = "ANACONDA_AUTH_KEYRING", "keyring"
    result = _env(key, what) or _secret(key, what)
    if not result:
        path = os.getenv("ANACONDA_KEYRING_PATH")
        path = expandvars(expanduser(path or "~/.anaconda/keyring"))
        result = _file(path, "keyring")
    return _keyring_to_api_key(result)


@cached
def get_api_key():
    api_key = None
    try:
        if not os.environ.get("ANACONDA_ANON_USAGE_STANDALONE"):
            api_key = _module()
        if api_key is None:
            api_key = _api_key()
            if api_key is None:
                api_key = _keyring()
    except Exception as exc:
        _debug("Unexpected exception obtaining API key: %s", exc)
    if api_key:
        return _jwt_to_token(api_key)
    return None, None
