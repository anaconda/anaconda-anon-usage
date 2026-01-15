# Search for conda packages in their canary/development channels.
# We want the latest version of each test package that is available
# across all platforms.

import io
import json
import re
import sys

from conda.cli.main import main
from conda.models.version import normalized_version

packages = {
    "conda": "conda-canary",
    "anaconda-anon-usage": "ctools",
}

subdirs = ["osx-arm64", "linux-64", "win-64"]


def _c(c):
    return "/".join(c.split("/")[3:-1])


def _p(*args):
    print(*args, file=sys.stderr)


data = {}
py_versions = None
for package, channel in packages.items():
    _p("")
    _p(f"Scanning for {package}")
    _p(f"  Channels: {channel}, {channel}/label/dev")
    p_records = {}
    versions = set()
    for subdir in subdirs:
        try:
            _stdout, sys.stdout = sys.stdout, io.StringIO()
            main(
                "search",
                "--platform",
                subdir,
                "-c",
                channel,
                "-c",
                channel + "/label/dev",
                "--override-channels",
                package,
                "--json",
            )
            t_data = json.loads(sys.stdout.getvalue()).get(package, [])
        finally:
            sys.stdout = _stdout
        p_records[subdir] = t_data
        n_versions = {(b["version"], _c(b["channel"])) for b in t_data}
        _p(f"  - {subdir}: {len(n_versions)} candidates")
        versions.update(n_versions)
    if not versions:
        continue
    _p("  Examining versions:")
    for version, channel in sorted(
        versions, key=lambda x: (normalized_version(x[0]), x[1]), reverse=True
    ):
        _p(f"  - version {version}, channel {channel}")
        q_records = {}
        for subdir in subdirs:
            builds = [
                b["build"]
                for b in p_records[subdir]
                if version == b["version"] and channel == _c(b["channel"])
            ]
            if builds:
                t_versions = {
                    re.sub(r"py3(\d+).*", r"3.\1", b)
                    for b in builds
                    if b.startswith("py3")
                }
                if subdir not in q_records or len(t_versions) > q_records[subdir]:
                    q_records[subdir] = t_versions
        if len(q_records) == len(subdirs):
            q_records = list(q_records.values())
            t_versions = q_records[0]
            if all(len(q) == len(t_versions) for q in q_records):
                data[package] = (version, channel)
                if t_versions:
                    _p(f"    Python versions: {', '.join(t_versions)}")
                    py_versions = (py_versions or t_versions) & t_versions
                break
        _p("    One or more builds are missing; trying the next version")

if len(data) < len(packages):
    missing = set(packages) - set(data)
    _p("")
    _p(f"Could not find canary candidate for: {','.join(missing)}")
    sys.exit(0)

if not py_versions:
    if py_versions is None:
        py_versions = ["3.10", "3.11", "3.12", "3.13"]
    else:
        _p("")
        _p("No Python version intersection across packages")
        sys.exit(0)

_p("")
_p("Final GitHub Action values:")
for package, (version, channel) in data.items():
    spec = f"{package}-spec={channel}::{package}={version}"
    _p(f"  {spec}")
    print(spec)
py_versions = json.dumps(sorted(py_versions, key=normalized_version))
spec = f"python-versions={py_versions}"
_p(f"  {spec}")
print(f"{spec}")
