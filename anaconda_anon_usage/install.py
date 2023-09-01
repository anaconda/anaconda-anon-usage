import argparse
import os
import sys
import sysconfig
from os.path import basename, dirname, exists, join, relpath
from traceback import format_exc


THIS_DIR = dirname(__file__)


def configure_parser():
    """Configure the given argparse parser instance"""
    p = argparse.ArgumentParser(description="The anaconda-anon-usage installer.")
    g = p.add_mutually_exclusive_group()
    g.add_argument(
        "--enable",
        action="store_true",
        help="Install the anaconda_anon_usage patch."
    )
    g.add_argument(
        "--disable", action="store_true",
        help="Remove the the anaconda_anon_usage patch."
    )
    g.add_argument(
        "--status",
        action="store_true",
        help="Print the anaconda_anon_usage patch status.",
    )
    p.add_argument(
        "--quiet",
        dest="verbose",
        action="store_false",
        default=True,
        help="Silent mode; disables all non-error output.",
    )
    return p


success = True


def error(what, fatal=False, warn=False):
    global success
    print("ERROR:", what)
    tb = format_exc()
    if not tb.startswith("NoneType"):
        print("-----")
        print(tb.rstrip())
        print("-----")
    if fatal:
        print("cannot proceed; exiting.")
        sys.exit(-1)
    if not warn:
        success = False


def tryop(op, *args, **kwargs):
    try:
        op(*args, **kwargs)
        return True
    except Exception:
        return False


PATCH_TEXT = b"""
# anaconda_anon_usage p2
try:
    import anaconda_anon_usage.patch
except Exception as exc:
    import os, sys
    print("Error loading anaconda_anon_usage:", exc, file=sys.stderr)
    if os.environ.get('ANACONDA_ANON_USAGE_RAISE'):
        raise
# anaconda_ident p1
"""

__sp_dir = None


def _sp_dir():
    global __sp_dir
    if __sp_dir is None:
        __sp_dir = sysconfig.get_paths()["purelib"]
    return __sp_dir


def _eolmatch(text, ptext):
    wineol = b"\r\n" in text
    if wineol != (b"\r\n" in ptext):
        args = (b"\n", b"\r\n") if wineol else (b"\r\n", b"\n")
        ptext = ptext.replace(*args)
    return ptext


def _read(args, pfile, patch_text, expect_no=False):
    if not exists(pfile):
        return None, "NOT PRESENT"
    with open(pfile, "rb") as fp:
        text = fp.read()
    patch_text = _eolmatch(text, patch_text)
    if text.endswith(patch_text):
        status = "NEEDS REMOVAL" if expect_no else "ENABLED"
    elif b"anaconda_ident" in text:
        status = "NEEDS REMOVAL" if expect_no else "NEEDS UPDATE"
    else:
        status = "DISABLED (not pro)" if expect_no else "DISABLED"
    return text, status


def _strip(text, patch_text):
    found = False
    patch_text = _eolmatch(text, patch_text)
    if text.endswith(patch_text):
        text = text[: -len(patch_text)]
        found = True
    if not found and b"# anaconda_ident " in text:
        text = text[: text.find(b"# anaconda_ident p")]
    return text


def _patch(args, pfile, patch_text, safety_len, expect_no):
    verbose = args.verbose or args.status
    if verbose:
        print(f"patch target: ...{relpath(pfile, _sp_dir())}")
    text, status = _read(args, pfile, patch_text, expect_no)
    if verbose:
        print(f"| status: {status}")
    if status == "NOT PRESENT":
        return
    elif status == "NEEDS UPDATE":
        need_change = True
        status = "removing" if args.disable else "updating"
    elif status == "NEEDS REMOVAL":
        need_change = True
        status = "removing"
    elif args.enable and not expect_no:
        need_change = status == "DISABLED"
        status = "applying"
    elif args.disable:
        need_change = status == "ENABLED"
        status = "removing"
    else:
        need_change = False
    if not need_change:
        return
    if verbose:
        print(f"| {status} patch...", end="")
    renamed = False
    try:
        text = _strip(text, patch_text)
        # safety valve
        if len(text) < safety_len:
            print("safety check failed")
            error("! unexpected error, no changes made", fatal=True)
        # We do not append to the original file because this is
        # likely a hard link into the package cache, so doing so
        # would lead to conda flagging package corruption.
        with open(pfile + ".new", "wb") as fp:
            fp.write(text)
            if status != "removing":
                fp.write(patch_text)
        pfile_orig = pfile + ".orig"
        if exists(pfile_orig):
            os.unlink(pfile_orig)
        os.rename(pfile, pfile_orig)
        renamed = True
        os.rename(pfile + ".new", pfile)
        if verbose:
            print("success")
    except Exception as exc:
        if verbose:
            what = "failed"
        else:
            what = f"failed to patch {relpath(pfile, _sp_dir())}"
        print(f"{what}: {exc}")
        if renamed:
            os.rename(pfile_orig, pfile)
    text, status = _read(args, pfile, patch_text)
    if verbose:
        print(f"| new status: {status}")


def manage_patch(args):
    if args.verbose or args.status:
        print("conda prefix:", sys.prefix)
    global PATCH_TEXT
    pfile = join(_sp_dir(), "conda", "base", "context.py")
    _patch(args, pfile, PATCH_TEXT, 70000, False)


def main(args=None):
    global success

    p = configure_parser()

    if args is None:
        sys.argv[0] = "anaconda-anon-usage"

    args = p.parse_args(args)

    verbose = args.verbose or args.status or len(sys.argv) <= 1
    if verbose:
        pkg_name = basename(dirname(__file__))
        msg = pkg_name + " installer"
        print(msg)
        msg = "-" * len(msg)
        print(msg)
        if len(sys.argv) <= 1:
            sys.argv[0] = "anaconda-anon-usage"
            print(msg)
            return 0
    manage_patch(args)
    if verbose:
        print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
