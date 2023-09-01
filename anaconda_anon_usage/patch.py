import base64
import os
import sys
from os.path import dirname, exists, expanduser, join

from conda.auxlib.decorators import memoize, memoizedproperty
from conda.base.context import Context, ParameterLoader, PrimitiveParameter, context
from conda.cli import install as cli_install

from . import __version__

DEBUG = bool(os.environ.get("ANACONDA_ANON_USAGE_DEBUG"))


def _debug(s, *args, error=False):
    if error or DEBUG:
        print(s % args, file=sys.stderr)


def get_random_token(nchar, bytes=None):
    if bytes is None:
        bytes = os.urandom((nchar * 6 - 1) // 8 + 1)
    return base64.urlsafe_b64encode(bytes)[:nchar].decode("ascii")


def get_saved_token(fpath, what, length=8):
    client_token = ""
    _debug("%s token path: %s", what.capitalize(), fpath)
    if exists(fpath):
        try:
            # Use just the first line of the file, if it exists
            client_token = "".join(open(fpath).read().splitlines()[:1])
            _debug("Retrieved %s token: %s", what, client_token)
        except Exception as exc:
            _debug("Unexpected error reading: %s\n  %s", fpath, exc, error=True)
    if len(client_token) < length:
        if len(client_token) > 0:
            _debug("Generating longer token")
        client_token = get_random_token(length)
        try:
            os.makedirs(dirname(fpath), exist_ok=True)
            with open(fpath, "w") as fp:
                fp.write(client_token)
            _debug("Generated new token: %s", client_token)
            _debug("%s token saved: %s", what.capitalize(), fpath)
        except Exception as exc:
            _debug("Unexpected error writing: %s\n  %s", fpath, exc, error=True)
            client_token = ""
    return client_token[:length]


def get_client_token():
    fpath = join(expanduser("~/.conda"), "aau_token")
    return get_saved_token(fpath, "client", 8)


def get_environment_token():
    try:
        prefix = context.checked_prefix or context.target_prefix
        if prefix is None:
            return None
    except Exception as exc:
        _debug("error retrieving prefix: %s", exc)
        return None
    fpath = join(prefix, "etc", "aau_token")
    return get_saved_token(fpath, "environment", 8)


@memoize
def client_token_string():
    parts = ["aau/" + __version__]
    value = get_client_token()
    if value:
        parts.append("c/" + value)
    parts.append("s/" + get_random_token(8))
    value = get_environment_token()
    if value:
        parts.append("e/" + value)
    result = " ".join(parts)
    _debug("Full client token: %s", result)
    return result


def _new_user_agent(ctx):
    result = ctx._old_user_agent
    if context.anaconda_anon_usage:
        token = client_token_string()
        if token:
            result += " " + token
    else:
        _debug("anaconda_anon_usage disabled by config")
    return result


def _new_check_prefix(prefix, json=False):
    context.checked_prefix = prefix
    cli_install._old_check_prefix(prefix, json)


# conda.base.context.Context.user_agent
# Adds the ident token to the user agent string
if not hasattr(Context, "_old_user_agent"):
    Context._old_user_agent = Context.user_agent
    # Using a different name ensures that this is stored
    # in sthe cache in a different place than the original
    Context.user_agent = memoizedproperty(_new_user_agent)

# conda.cli.install.check_prefix
# Collects the prefix computed there so that we can properly
# detect the creation of environments using "conda env create"
if not hasattr(cli_install, "_old_check_prefix"):
    cli_install._old_check_prefix = cli_install.check_prefix
    cli_install.check_prefix = _new_check_prefix
    context.checked_prefix = None

# conda.base.context.Context
# Adds anaconda_ident as a managed string config parameter
if not hasattr(Context, "anaconda_anon_usage"):
    _param = ParameterLoader(PrimitiveParameter(True))
    Context.anaconda_anon_usage = _param
    Context.parameter_names += (_param._set_name("anaconda_anon_usage"),)
