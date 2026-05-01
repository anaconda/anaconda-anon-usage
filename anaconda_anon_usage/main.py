"""Command-line entry point for the ``anaconda-anon-usage`` executable."""

import os
import sys

from . import __version__
from .tokens import (
    INSTALLER_TOKEN_NAME,
    MACHINE_TOKEN_NAME,
    ORG_TOKEN_NAME,
    _search_path,
    _system_tokens,
    all_tokens,
    token_string,
)
from .utils import _random_token


def _print_help():
    print(f"anaconda-anon-usage {__version__} (Python package)")
    print()
    print("Usage: anaconda-anon-usage [options]")
    print()
    print("Options:")
    print("  --verbose          Increase verbosity")
    print("  --detail           Print per-token provenance")
    print("  --prefix PATH      Use PATH as the environment prefix")
    print("  --jwt TOKEN        Use TOKEN as the Anaconda auth JWT")
    print("  --no-keyring       Disable keyring lookups")
    print("  --paths            Print the system token search path")
    print("  --random           Generate and print a random token")
    print("  --version          Print the package version")


def main():
    """CLI for testing anaconda-anon-usage token generation."""
    args = sys.argv[1:]

    verbosity = 0
    prefix = None
    detail = False
    no_keyring = False
    jwt = None

    while args:
        if args[0] == "--verbose":
            verbosity += 1
            args.pop(0)
        elif args[0] == "--help":
            _print_help()
            sys.exit(0)
        elif args[0] == "--version":
            print(__version__)
            sys.exit(0)
        elif args[0] == "--paths":
            for p in _search_path():
                print(p)
            sys.exit(0)
        elif args[0] == "--random":
            print(_random_token())
            sys.exit(0)
        elif args[0] == "--prefix":
            args.pop(0)
            prefix = args.pop(0) if args else None
            if prefix is None:
                print("--prefix requires a value", file=sys.stderr)
                sys.exit(1)
        elif args[0] == "--jwt":
            args.pop(0)
            jwt = args.pop(0) if args else None
            if jwt is None:
                print("--jwt requires a value", file=sys.stderr)
                sys.exit(1)
        elif args[0] == "--detail":
            detail = True
            args.pop(0)
        elif args[0] == "--no-keyring":
            no_keyring = True
            args.pop(0)
        else:
            print(f"Unknown option: {args[0]}", file=sys.stderr)
            sys.exit(1)

    if verbosity:
        from . import utils

        utils.DEBUG = True
    if jwt:
        os.environ["ANACONDA_AUTH_API_KEY"] = jwt
    elif no_keyring:
        os.environ["ANACONDA_DOMAIN"] = "__disabled__"

    print(token_string(prefix))
    if detail:
        tokens = all_tokens(prefix)
        field_info = [
            ("c", "client", tokens.client, "~/.conda/aau_token"),
            ("s", "session", tokens.session, "random (per-process)"),
            (
                "e",
                "environment",
                tokens.environment,
                f"{prefix or '$CONDA_PREFIX'}/etc/aau_token",
            ),
            ("a", "anaconda", tokens.anaconda_cloud, "jwt (sub claim)"),
        ]
        for pfx, label, value, source in field_info:
            if value:
                print(f"  {pfx}/{value} ({label}) <- {source}")
        for pfx, label, fname in [
            ("i", "installer", INSTALLER_TOKEN_NAME),
            ("o", "organization", ORG_TOKEN_NAME),
            ("m", "machine", MACHINE_TOKEN_NAME),
        ]:
            for v, source in _system_tokens(fname, label, with_source=True):
                print(f"  {pfx}/{v} ({label}) <- {source}")


if __name__ == "__main__":
    main()
