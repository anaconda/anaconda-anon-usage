#!/bin/sh

pfx="${CONDA_PREFIX:-${PREFIX:-}}"
pbin="${pfx}/python.exe"
[ -f "${pbin}" ] || pbin="${pfx}/bin/python"
"${pbin}" -m anaconda_anon_usage.install --enable --quiet >>"${pfx}/.messages.txt" 2>&1 || :
