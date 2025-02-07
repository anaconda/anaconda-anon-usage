import json
import os
import re
import subprocess
import sys
from os.path import basename, dirname, expanduser, isfile, join

from anaconda_anon_usage import tokens as m_tokens

nfailed = 0

KEY = "anaconda_anon_usage"
ENVKEY = "CONDA_ANACONDA_ANON_USAGE"
DEBUG_PREFIX = os.environ.get("ANACONDA_ANON_USAGE_DEBUG_PREFIX")
# Make sure we always try to fetch. Prior versions of this
# test code used a fake channel to accomplish this, but the
# fetch behavior of conda changed to frustrate that approach.
os.environ["CONDA_LOCAL_REPODATA_TTL"] = "0"
FAST_EXIT = "--fast" in sys.argv

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


def _config(value, ctype):
    if ctype == "env":
        os.environ[ENVKEY] = value
    elif ENVKEY in os.environ:
        del os.environ[ENVKEY]
    cvalue = "true" if ctype == "env" or value == "default" else value
    subprocess.run(["conda", "config", "--set", KEY, cvalue], capture_output=True)
    if ctype == "env" or value == "default":
        subprocess.run(["conda", "config", "--remove-key", KEY], capture_output=True)
    return value in yes_modes


all_modes = ["true", "false", "yes", "no", "on", "off", "default"]
yes_modes = ("true", "yes", "on", "default")
all_tokens = {"aau", "c", "s", "e"}
aau_only = {"aau"}
if m_tokens.organization_token():
    all_tokens.add("o")
if m_tokens.machine_token():
    all_tokens.add("m")
if m_tokens.anaconda_cloud_token():
    all_tokens.add("a")

proc = subprocess.run(
    ["conda", "info", "--envs", "--json"],
    check=False,
    capture_output=True,
    text=True,
)
pdata = json.loads(proc.stdout)
pfx_s = join(sys.prefix, "envs") + os.sep
envs = [e for e in pdata["envs"] if e == sys.prefix or e.startswith(pfx_s)]
envs = {("base" if e == sys.prefix else basename(e)): e for e in envs}
for env in envs:
    # Test each env twice to confirm that
    # we get the same token each time
    all_modes.append("e/" + env)
    all_modes.append("e/" + env)
maxlen = max(6, max(len(e) for e in envs))

first = True
other_tokens = {}
all_sessions = set()
all_environments = set()
for ctype in ("env", "cfg"):
    for mode in all_modes:
        if mode.startswith("e/"):
            mode, envname = "default", mode[2:]
            envpath = envs[envname]
        else:
            envname = envpath = ""
        if mode == "default" and ctype == "env":
            continue
        enabled = _config(mode, ctype)
        # Using proxyspy allows us to test this without the requests actually
        # making it to repo.anaconda.com. The tester returns 404 for all requests.
        # It also has the advantage of making sure our code respects proxies
        # fmt: off
        cmd = ["proxyspy", "--return-code", "404", "--",
               "conda", "install", "--override-channels",
               "-c", "defaults", "fakepackage"]
        # fmt: on
        if envname:
            cmd.extend(["-n", envname])
        skip = False
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
        match = re.search(r"^.*User-Agent: (.+)$", proc.stdout, re.MULTILINE)
        user_agent = match.groups()[0] if match else ""
        if first:
            if user_agent:
                print(user_agent)
            print("")
            print("Configuration tests")
            print("-" * (maxlen + 19))
            first = False
        if not user_agent or skip:
            print(f"{ctype} {mode:<7} | {envname:{maxlen}} | ERROR")
            for line in proc.stderr.splitlines():
                if line.strip():
                    print("|", line)
            if user_agent:
                print("|", user_agent)
            nfailed += 1
            if FAST_EXIT:
                break
            continue
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
        duplicated = []
        for k, v in tokens.items():
            if k == "s":
                if v in all_sessions:
                    duplicated.append("s")
                all_sessions.add(v)
                continue
            if k == "e":
                k = "e/" + (envname or "base")
                if k not in other_tokens and v in all_environments:
                    duplicated.append("e")
                all_environments.add(v)
            if other_tokens.setdefault(k, v) != v:
                modified.append(k.split("/")[0])
        if duplicated:
            status.append(f"DUPLICATED: {','.join(duplicated)}")
        if modified:
            status.append(f"MODIFIED: {','.join(modified)}")
        if status:
            nfailed += 1
            status = ", ".join(status)
        else:
            status = "OK"
        emsg = envname or "<base>"
        print(f"{ctype} {mode:<7} | {emsg:{maxlen}} | {status}")
        if DEBUG_PREFIX:
            for line in proc.stderr.splitlines():
                if line.startswith(DEBUG_PREFIX):
                    print("|", line[4:])
        if status != "OK" or DEBUG_PREFIX:
            print("|", user_agent)
        if status != "OK" and FAST_EXIT:
            break
print("-" * (maxlen + 19))

print("")
if f_mode == "missing":
    print("removing ~/.condarc")
    try:
        os.unlink(condarc)
    except Exception as exc:
        print("error removing ~/.condarc:", exc)
        pass
elif f_mode == "default":
    print("removing config value")
    _config("default", "cfg")
else:
    print("restoring config value:", f_mode)
    _config(f_mode, "cfg")

print("")
print("Checking environment tokens")
print("---------------------------")
for k, v in other_tokens.items():
    if k.startswith("e/"):
        pfx = envs[k[2:]]
        tpath = join(pfx, "etc", "aau_token")
        try:
            with open(tpath) as fp:
                token = fp.read().strip()
        except Exception:
            token = ""
        status = "OK" if token == v else "XX"
        print(f"{k[2:]:{maxlen}} | {v} {token} | {status}")
        if token != v:
            nfailed += 1
print("---------------------------")

print("")
print("FAILURES:", nfailed)
sys.exit(nfailed)
