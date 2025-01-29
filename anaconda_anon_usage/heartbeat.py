"""
This module implements a heartbeat function that sends a simple
HEAD request to an upstream repository. It can be configured to
trigger upon environment activation, but it is off by default.
The intended use case is for organizations to enable it through
system configuration for better usage tracking.
"""

import argparse
import os
import sys
from threading import Thread

from conda.base.context import context
from conda.gateways.connection.session import CondaSession
from conda.models.channel import Channel

from . import utils

VERBOSE = False
STANDALONE = False
DRY_RUN = os.environ.get("ANACONDA_HEARTBEAT_DRY_RUN")

CLD_REPO = "https://repo.anaconda.cloud"
ORG_REPO = "https://conda.anaconda.org"
COM_REPO = "https://repo.anaconda.com/pkgs"
HEARTBEAT_PATH = "/noarch/activate-0.0.0-0.conda"


def _print(msg, *args, standalone=False, error=False):
    global VERBOSE
    global STANDALONE
    if not (VERBOSE or utils.DEBUG or error):
        return
    if standalone and not STANDALONE:
        return
    # It is very important that these messages are printed to stderr
    # when called from within the activate script. Otherwise they
    # will insert themselves into the activation command set
    ofile = sys.stdout if STANDALONE and not (error or utils.DEBUG) else sys.stderr
    print(msg % args, file=ofile)


def _ping(session, url, wait):
    try:
        response = session.head(url, proxies=session.proxies)
        _print("Status code (expect 404): %s", response.status_code)
    except Exception as exc:
        if type(exc).__name__ != "ConnectionError":
            _print("Heartbeat error: %s", exc, error=True)


def attempt_heartbeat(channel=None, path=None, wait=False):
    global DRY_RUN
    line = "------------------------"
    _print(line, standalone=True)
    _print("anaconda-ident heartbeat", standalone=True)
    _print(line, standalone=True)

    if not hasattr(context, "_aau_initialized"):
        from . import patch

        patch.main()

    if channel and "/" in channel:
        url = channel
    else:
        # Silences the defaults deprecation error
        if not context._channels:
            context._channels = ["defaults"]
        urls = [u for c in context.channels for u in Channel(c).urls()]
        urls.extend(u.rstrip("/") for u in context.channel_alias.urls())
        if any(u.startswith(CLD_REPO) for u in urls):
            base = CLD_REPO
        elif any(u.startswith(COM_REPO) for u in urls):
            base = COM_REPO
        elif any(u.startswith(ORG_REPO) for u in urls):
            base = ORG_REPO
        else:
            _print("No valid heartbeat channel")
            _print(line, standalone=True)
            return
        url = base + "/" + (channel or "main")
    url = url.rstrip("/") + "/" + (path or HEARTBEAT_PATH).lstrip("/")

    _print("Heartbeat url: %s", url)
    _print("User agent: %s", context.user_agent)
    if DRY_RUN:
        _print("Dry run selected, not sending heartbeat.")
    else:
        session = CondaSession()
        t = Thread(target=_ping, args=(session, url, wait), daemon=True)
        t.start()
        _print("%saiting for response", "W" if wait else "Not w")
        t.join(timeout=None if wait else 0.1)
    _print(line, standalone=True)


def main():
    global VERBOSE
    global DRY_RUN
    p = argparse.ArgumentParser()
    p.add_argument("--channel", default=None)
    p.add_argument("--path", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--wait", action="store_true")
    args = p.parse_args()
    VERBOSE = args.verbose
    DRY_RUN = args.dry_run
    attempt_heartbeat(args.channel, args.path, args.wait)


if __name__ == "__main__":
    STANDALONE = True
    main()
