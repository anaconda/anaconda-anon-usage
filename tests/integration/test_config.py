import os
import subprocess
import sys
from os.path import expanduser, isfile, join

nfailed = 0

KEY = "anaconda_anon_usage"
ENVKEY = "CONDA_ANACONDA_ANON_USAGE"
os.environ["ANACONDA_ANON_USAGE_DEBUG"] = "1"

condarc = join(expanduser("~"), ".condarc")
if not isfile(condarc):
    f_mode = "missing"
else:
    with open(condarc) as fp:
        values = fp.read()
    f_mode = "default"
    for line in values.splitlines():
        if line.startswith(KEY):
            f_mode = line.split(":", 1)[-1].strip()
print("current condarc mode:", f_mode)


def _config(value):
    if value == "default":
        _config("true")
        subprocess.run(["conda", "config", "--remove-key", KEY])
    else:
        subprocess.run(["conda", "config", "--set", KEY, value])


all_modes = ("true", "false", "yes", "no", "on", "off", "default")
yes_modes = ("true", "yes", "on", "default")
all_tokens = {"aau", "c", "s", "e"}
aau_only = {"aau"}


other_tokens = {}
all_sessions = set()
for ctype in ("env", "cfg"):
    if ctype == "cfg" and ENVKEY in os.environ:
        del os.environ[ENVKEY]
    for mode in all_modes:
        if mode == "default" and ctype == "env":
            continue
        enabled = mode in yes_modes
        if ctype == "env":
            os.environ[ENVKEY] = mode
            _config("false" if enabled else "true")
        else:
            _config(mode)
        # Make sure to leave override-channels and the full channel URL in here.
        # This allows this command to run fully no matter what we do to channel_alias
        # and default_channels
        proc = subprocess.run(
            [
                "conda",
                "search",
                "-vvv",
                "--override-channels",
                "-c",
                "https://repo.anaconda.com/pkgs/fakechannel",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        user_agent = [v for v in proc.stderr.splitlines() if "User-Agent" in v]
        user_agent = user_agent[0].split(":", 1)[-1].strip() if user_agent else ""
        print(user_agent)
        tokens = dict(t.split("/", 1) for t in user_agent.split())
        tokens = {k: v for k, v in tokens.items() if k in all_tokens}
        status = []
        expected = all_tokens if enabled else aau_only
        missing = expected - set(tokens)
        extras = set(tokens) - expected
        if missing:
            status.append(f"MISSING: {'/'.join(missing)}")
        if extras:
            status.append(f"NOT CLEARED: {'/'.join(extras)}")
        modified = []
        for k, v in tokens.items():
            if k == "s":
                if v in all_sessions:
                    status.append("DUPLICATE: s")
            elif other_tokens.setdefault(k, v) != v:
                modified.append(k)
        if modified:
            status.append(f"MODIFIED: {'/'.join(modified)}")
        if status:
            nfailed += 1
            status = ", ".join(status)
        else:
            status = "OK"
        print(
            f"{ctype}/{mode}:", status, " ".join(f"{k}/{v}" for k, v in tokens.items())
        )

if f_mode == "missing":
    print("removing ~/.condarc")
    try:
        os.unlink(condarc)
    except Exception as exc:
        print("error removing ~/.condarc:", exc)
        pass
elif f_mode == "default":
    print("removing config value")
    _config("default")
else:
    print("restoring config value:", f_mode)
    _config(f_mode)

print("FAILURES:", nfailed)
sys.exit(nfailed)
