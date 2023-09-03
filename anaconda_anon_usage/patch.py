import base64
import functools
import os
import sys
from os.path import dirname, exists, expanduser, join
from uuid import uuid4

from conda.auxlib.decorators import memoizedproperty
from conda.base.context import Context, ParameterLoader, PrimitiveParameter, context

from . import __version__

DEBUG = bool(os.environ.get("ANACONDA_ANON_USAGE_DEBUG"))


def _debug(s, *args, error=False):
    if error or DEBUG:
        print(s % args, file=sys.stderr)


def get_random_token():
    return base64.urlsafe_b64encode(uuid4().bytes).strip(b"=").decode("ascii")


def get_saved_token(fpath, what):
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
        client_token = get_random_token()
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


def get_client_token():
    fpath = join(expanduser("~/.conda"), "aau_token")
    return get_saved_token(fpath, "client")


def get_environment_token():
    try:
        prefix = Context.checked_prefix or context.target_prefix
        if prefix is None:
            return None
    except Exception as exc:
        _debug("error retrieving prefix: %s", exc)
        return None
    fpath = join(prefix, "etc", "aau_token")
    return get_saved_token(fpath, "environment")


@functools.lru_cache(maxsize=None)
def client_token_string():
    parts = ["aau/" + __version__]
    value = get_client_token()
    if value:
        parts.append("c/" + value)
    parts.append("s/" + get_random_token())
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


def main(plugin=False):
    if hasattr(Context, "_old_user_agent"):
        _debug("anaconda_anon_usage already active")
        return
    _debug("Applying anaconda_anon_usage context patch")

    # conda.base.context.Context.user_agent
    # Adds the ident token to the user agent string
    Context._old_user_agent = Context.user_agent
    # Using a different name ensures that this is stored
    # in the cache in a different place than the original
    Context.user_agent = memoizedproperty(_new_user_agent)

    # conda.base.context.Context
    # Adds anaconda_anon_usage as a managed string config parameter
    _param = ParameterLoader(PrimitiveParameter(True))
    Context.anaconda_anon_usage = _param
    Context.parameter_names += (_param._set_name("anaconda_anon_usage"),)

    # conda.base.context.checked_prefix
    # Saves the prefix used in a conda install command
    Context.checked_prefix = None

    def _new_check_prefix(prefix, json=False):
        Context.checked_prefix = prefix
        Context._old_check_prefix(prefix, json)

    def _patch_check_prefix():
        _debug("Applying anaconda_anon_usage cli.install patch")
        from conda.cli import install as cli_install

        Context._old_check_prefix = cli_install.check_prefix
        cli_install.check_prefix = _new_check_prefix

    if plugin:
        # The pre-command plugin avoids the circular import
        # of conda.cli.install, so we can apply the patch now
        _patch_check_prefix()
    else:
        # We need to delay further. Schedule the patch for the
        # next time context.__init__ is called.
        _debug("Deferring anaconda_anon_usage cli.install patch")
        _old__init__ = context.__init__

        def _new_init(*args, **kwargs):
            _patch_check_prefix()
            context.__init__ = _old__init__
            _old__init__(*args, **kwargs)

        context.__init__ = _new_init
