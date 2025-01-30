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
from urllib.parse import urljoin

from conda.base.context import context
from conda.gateways.connection.session import get_session
from conda.models.channel import Channel

from . import utils

VERBOSE = False
STANDALONE = False
DRY_RUN = os.environ.get("ANACONDA_HEARTBEAT_DRY_RUN")

CLD_REPO = "https://repo.anaconda.cloud/"
ORG_REPO = "https://conda.anaconda.org/"
COM_REPO = "https://repo.anaconda.com/pkgs/"
REPOS = (CLD_REPO, COM_REPO, ORG_REPO)
HEARTBEAT_PATH = "noarch/activate-0.0.0-0.conda"


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
    _print("anaconda-anon-usage heartbeat", standalone=True)
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
        for base in REPOS:
            if any(u.startswith(base) for u in urls):
                break
        else:
            _print("No valid heartbeat channel")
            _print(line, standalone=True)
            return
        url = urljoin(base, channel or "main") + "/"
    url = urljoin(url, path or HEARTBEAT_PATH)

    _print("Heartbeat url: %s", url)
    _print("User agent: %s", context.user_agent)
    if DRY_RUN:
        _print("Dry run selected, not sending heartbeat.")
    else:
        session = get_session(url)
        t = Thread(target=_ping, args=(session, url, wait), daemon=True)
        t.start()
        _print("%saiting for response", "W" if wait else "Not w")
        t.join(timeout=None if wait else 0.1)
    _print(line, standalone=True)


def main():
    global VERBOSE
    global DRY_RUN
    global STANDALONE
    p = argparse.ArgumentParser()
    p.add_argument("-c", "--channel", default=None)
    p.add_argument("-p", "--path", default=None)
    p.add_argument("-d", "--dry-run", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("-w", "--wait", action="store_true")
    args = p.parse_args()
    STANDALONE = True
    VERBOSE = not args.quiet
    DRY_RUN = args.dry_run
    attempt_heartbeat(args.channel, args.path, args.wait)


if __name__ == "__main__":
    main()
