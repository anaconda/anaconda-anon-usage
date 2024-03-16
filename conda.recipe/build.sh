#!/bin/bash
"${PREFIX}/bin/python" -m pip install --no-deps --ignore-installed -vv .
if [ "$NEED_SCRIPTS" != yes ]; then
    rm ${SP_DIR}/anaconda_anon_usage/install.py
    exit 0
fi
rm ${SP_DIR}/anaconda_anon_usage/plugin.py
mkdir -p "${PREFIX}/etc/conda/activate.d" "${PREFIX}/bin"
cp "scripts/activate.sh" "${PREFIX}/etc/conda/activate.d/${PKG_NAME}_activate.sh"
cp "scripts/post-link.sh" "${PREFIX}/bin/.${PKG_NAME}-post-link.sh"
cp "scripts/pre-unlink.sh" "${PREFIX}/bin/.${PKG_NAME}-pre-unlink.sh"
cp "scripts/activate.bat" "${PREFIX}/etc/conda/activate.d/${PKG_NAME}_activate.bat"
cp "scripts/post-link.bat" "${PREFIX}/bin/.${PKG_NAME}-post-link.bat"
cp "scripts/pre-unlink.bat" "${PREFIX}/bin/.${PKG_NAME}-pre-unlink.bat"
