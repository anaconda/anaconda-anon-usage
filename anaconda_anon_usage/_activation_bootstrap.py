import os
import sys


def maybe_patch_activation(argv=None):
    if argv is None:
        argv = sys.argv
    if len(argv) < 3 or not argv[1].startswith("shell.") or argv[2] != "activate":
        return False

    try:
        from . import patch

        return patch.main(plugin=True, command="activate")
    except Exception as exc:
        if os.environ.get("ANACONDA_ANON_USAGE_RAISE"):
            raise
        if os.environ.get("ANACONDA_ANON_USAGE_DEBUG"):
            print(
                "Error loading anaconda-anon-usage activation bootstrap: %s" % exc,
                file=sys.stderr,
            )
    return False
