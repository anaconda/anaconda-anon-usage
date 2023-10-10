pbin="${CONDA_PREFIX}/python.exe"
[ -f "${pbin}" ] || pbin="${CONDA_PREFIX}/bin/python"
"${pbin}" -m anaconda_anon_usage.install --enable --quiet || :
