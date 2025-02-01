"""
This module implements a heartbeat function that sends a simple
HEAD request to an upstream repository. It can be configured to
trigger upon environment activation, but it is off by default.
The intended use case is for organizations to enable it through
system configuration for better usage tracking.
"""

import argparse
import sys
from threading import Thread
from urllib.parse import urljoin

from conda.base.context import context
from conda.gateways.connection.session import get_session
from conda.models.channel import Channel

from . import utils

VERBOSE = False
STANDALONE = False

CLD_REPO = "https://repo.anaconda.cloud/"
ORG_REPO = "https://conda.anaconda.org/"
COM_REPO = "https://repo.anaconda.com/pkgs/"
REPOS = (CLD_REPO, COM_REPO, ORG_REPO)
HEARTBEAT_PATH = "noarch/activate-0.0.0-0.conda"
# How long to attempt the connection. When a connection to our
# repository is blocked or slow, a long timeout would lead to
# a slow activation and a poor user experience. This is a total
# timeout value, split between attempts and backoffs.
TIMEOUT = 0.4
RETRIES = 3


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


def _ping(session, url, wait, timeout):
    try:
        # A short timeout is necessary here so that the activation
        # is not unduly delayed by a blocked internet connection
        response = session.head(url, proxies=session.proxies, timeout=timeout)
        _print("Status code (expect 404): %s", response.status_code)
    except Exception as exc:
        if type(exc).__name__ != "ConnectionError":
            _print("Unexpected heartbeat error: %s", exc, error=True)
        elif "timeout=" in str(exc):
            _print("Timeout exceeded; heartbeat likely not sent.")


def attempt_heartbeat(channel=None, path=None, wait=False, dry_run=False):
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
    if dry_run:
        _print("Dry run selected, not sending heartbeat.")
    else:
        # No backoff is applied between the first and second attempts
        n_blocks = RETRIES + 2 ** max(RETRIES - 2, 0) - 1
        timeout = TIMEOUT / n_blocks
        context.remote_max_retries = RETRIES
        context.remote_backoff_factor = timeout
        session = get_session(url)
        # Run in the background so we can proceed with the rest of the
        # activation tasks while the request fires. The process will wait
        # to terminate until the thread is complete.
        t = Thread(target=_ping, args=(session, url, wait, timeout), daemon=False)
        t.start()
    _print(line, standalone=True)


def main():
    global VERBOSE
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
    attempt_heartbeat(args.channel, args.path, args.wait, args.dry_run)


if __name__ == "__main__":
    main()
