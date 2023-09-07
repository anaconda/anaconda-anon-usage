import base64
import os
import sys
from os.path import dirname, exists
from uuid import uuid4

DEBUG = bool(os.environ.get("ANACONDA_ANON_USAGE_DEBUG"))


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
            with open(fpath) as fp:
                client_token = "".join(fp.read().splitlines()[:1])
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
