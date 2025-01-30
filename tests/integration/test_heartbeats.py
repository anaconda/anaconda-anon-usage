import json
import os
import re
import subprocess
import sys

from conda.base.context import context
from conda.models.channel import Channel

from anaconda_anon_usage import __version__ as aau_version
from anaconda_anon_usage import patch

patch.main()
context.__init__()
expected = ("aau", "c", "s", "e")
can_disable = True
if os.path.isfile("/etc/conda/org_token"):
    expected += ("o",)
if os.path.isfile("/etc/conda/machine_token"):
    expected += ("m",)

os.environ["ANACONDA_ANON_USAGE_DEBUG"] = "1"
os.environ["ANACONDA_HEARTBEAT_DRY_RUN"] = "1"

ALL_FIELDS = {"aau", "aid", "c", "s", "e", "u", "h", "n", "m", "o", "U", "H", "N"}


def get_test_envs():
    proc = subprocess.run(
        ["conda", "info", "--envs", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )
    pfx_s = os.path.join(sys.prefix, "envs") + os.sep
    pdata = json.loads(proc.stdout)
    # Limit ourselves to two non-base environments to speed up local testing
    envs = [sys.prefix] + [e for e in pdata["envs"] if e.startswith(pfx_s)][:2]
    envs = {("base" if e == sys.prefix else os.path.basename(e)): e for e in envs}
    return envs


envs = get_test_envs()
maxlen = max(len(e) for e in envs)
nfailed = 0
other_tokens = {"aau": aau_version}
all_session_tokens = set()
all_environments = set()


def verify_user_agent(output, expected, envname=None, marker=None):
    # Unfortunately conda has evolved how it logs request headers
    # So this regular expression attempts to match multiple forms
    # > User-Agent: conda/...
    # .... {'User-Agent': 'conda/...', ...}
    other_tokens["n"] = envname if envname else "base"

    user_agent = ""
    marker = marker or "User-Agent"
    MATCH_RE = r".*" + marker + r'(["\']?): *(["\']?)(.+)'
    for v in output.splitlines():
        match = re.match(MATCH_RE, v)
        if match:
            _, delim, user_agent = match.groups()
            if delim and delim in user_agent:
                user_agent = user_agent.split(delim, 1)[0]
            break

    new_values = [t.split("/", 1) for t in user_agent.split(" ") if "/" in t]
    new_values = {k: v for k, v in new_values if k in ALL_FIELDS}
    header = " ".join(f"{k}/{v}" for k, v in new_values.items())

    # Confirm that all of the expected tokens are present
    status = []
    missing = set(expected) - set(new_values)
    extras = set(new_values) - set(expected)
    if missing:
        status.append(f"{','.join(missing)} MISSING")
    if extras:
        status.append(f"{','.join(extras)} EXTRA")
    modified = []
    duplicated = []
    for k, v in new_values.items():
        if k == "s":
            if new_values["s"] in all_session_tokens:
                status.append("SESSION")
            all_session_tokens.add(new_values["s"])
            continue
        if k == "e":
            k = "e/" + (envname or "base")
            if k not in other_tokens and v in all_environments:
                duplicated.append("e")
            all_environments.add(v)
        if other_tokens.setdefault(k, v) != v:
            modified.append(k)
    if duplicated:
        status.append(f"DUPLICATED: {','.join(duplicated)}")
    if modified:
        status.append(f"MODIFIED: {','.join(modified)}")
    return ", ".join(status), header


if len(sys.argv) > 1:
    shells = sys.argv[1:]
else:
    shells = ["posix", "cmd.exe", "powershell"]
shells = shells + shells
print("Testing heartbeat")
print("-----------------")
urls = [u for c in context.channels for u in Channel(c).urls()]
urls.extend(u.rstrip("/") for u in context.channel_alias.urls())
if any(".anaconda.cloud" in u for u in urls):
    hb_url = "https://repo.anaconda.cloud/"
elif any(".anaconda.com" in u for u in urls):
    hb_url = "https://repo.anaconda.com/"
elif any(".anaconda.org" in u for u in urls):
    hb_url = "https://conda.anaconda.org/"
else:
    hb_url = None
if hb_url:
    hb_url += "pkgs/main/noarch/activate-0.0.0-0.conda"
print("Expected heartbeat url:", hb_url)
print("Expected user agent tokens:", ",".join(expected))
need_header = True
for hval in ("true", "false"):
    os.environ["CONDA_ANACONDA_HEARTBEAT"] = hval
    for envname in envs:
        # Do each one twice to make sure the user agent string
        # remains correct on repeated attempts
        for stype in shells:
            cmd = ["conda", "shell." + stype, "activate", envname]
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
            header = status = ""
            no_hb_url = "No valid heartbeat channel" in proc.stderr
            hb_urls = {
                line.rsplit(" ", 1)[-1]
                for line in proc.stderr.splitlines()
                if "Heartbeat url:" in line
            }
            status = ""
            if hval == "true":
                if not (no_hb_url or hb_urls):
                    status = "NOT ENABLED"
                elif hb_url and not hb_urls:
                    status = "NO HEARTBEAT URL"
                elif not hb_url and hb_urls:
                    status = "UNEXPECTED URLS: " + ",".join(hb_urls)
                elif hb_url and any(hb_url not in u for u in hb_urls):
                    status = "INCORRECT URLS: " + ",".join(hb_urls)
            elif hval == "false" and (no_hb_url or hb_urls):
                status = "NOT DISABLED"
            if hb_urls and not status:
                status, header = verify_user_agent(
                    proc.stderr, expected, envname, "Full client token"
                )
            if need_header:
                if header:
                    print("|", header)
                print(f"hval  shell      {'envname':{maxlen}} status")
                print(f"----- ---------- {'-' * maxlen} ----------")
                need_header = False
            print(f"{hval:5} {stype:10} {envname:{maxlen}} {status or 'OK'}")
            if status:
                print("|", " ".join(cmd))
                for line in proc.stderr.splitlines():
                    if line.strip():
                        print("!", line)
                if header:
                    print("|", header)
                nfailed += 1

print("FAILURES:", nfailed)
sys.exit(nfailed)
