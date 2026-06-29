"""Bootstrap activation patching from Python startup hooks.

Normal conda commands use the conda pre-command plugin, but recent conda
activation can bypass plugin loading on the shell activation fast path. This
module is imported by startup hook files and then checks ``sys.argv`` before
loading the heavier patching code, so unrelated Python startup remains cheap.
"""

import os
import sys


def maybe_patch_activation(argv=None):
    if argv is None:
        argv = sys.argv
    if len(argv) < 3 or not argv[1].startswith("shell.") or argv[2] != "activate":
        return False

    try:
        # Keep this lazy. Python startup hooks may import this module for
        # non-activation processes, but only activation needs conda patching.
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
