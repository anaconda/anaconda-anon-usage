import base64
import os
import sys
from os.path import dirname, exists
from threading import RLock

DPREFIX = os.environ.get("ANACONDA_ANON_USAGE_DEBUG_PREFIX") or ""
DEBUG = bool(os.environ.get("ANACONDA_ANON_USAGE_DEBUG")) or DPREFIX


# While lru_cache is thread safe, it does not prevent two threads
# from beginning the same computation. This simple cache mechanism
# uses a lock to ensure that only one thread even attempts.
CACHE = {}
LOCK = RLock()


def cached(func):
    def call_if_needed(*args, **kwargs):
        global CACHE
        key = (func.__name__, args, tuple(kwargs.items()))
        if key not in CACHE:
            with LOCK:
                # Need to check again, just in case the
                # computation was happening between the
                # first check and the lock acquisition.
                if key not in CACHE:
                    CACHE[key] = func(*args, **kwargs)
        return CACHE[key]

    return call_if_needed


def _debug(s, *args, error=False):
    if error or DEBUG:
        print((DPREFIX + s) % args, file=sys.stderr)


def _random_token(what):
    data = os.urandom(16)
    result = base64.urlsafe_b64encode(data).strip(b"=").decode("ascii")
    _debug("Generated %s token: %s", what, result)
    return result


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
            with open(fpath) as fp:
                client_token = "".join(fp.read().splitlines()[:1])
            _debug("Retrieved %s token: %s", what, client_token)
        except Exception as exc:
            _debug("Unexpected error reading: %s\n  %s", fpath, exc, error=True)
    if len(client_token) < 22:
        if len(client_token) > 0:
            _debug("Generating longer token")
        client_token = _random_token(what)
        try:
            os.makedirs(dirname(fpath), exist_ok=True)
            with open(fpath, "w") as fp:
                fp.write(client_token)
            _debug("%s token saved: %s", what.capitalize(), fpath)
        except Exception as exc:
            _debug("Unexpected error writing: %s\n  %s", fpath, exc, error=True)
            client_token = ""
    return client_token
