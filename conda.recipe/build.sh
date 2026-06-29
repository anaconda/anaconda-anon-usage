#!/bin/bash
"${PREFIX}/bin/python" -m pip install --no-deps --ignore-installed -vv .
if [ "$NEED_SCRIPTS" != yes ]; then
    rm ${SP_DIR}/anaconda_anon_usage/install.py
    # Ship both Python startup hook forms: .pth for current Python releases and
    # .start for PEP 829-capable Python releases.
    cp \
        "scripts/anaconda_anon_usage_activation.pth" \
        "${SP_DIR}/anaconda_anon_usage_activation.pth"
    cp \
        "scripts/anaconda_anon_usage_activation.start" \
        "${SP_DIR}/anaconda_anon_usage_activation.start"
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
