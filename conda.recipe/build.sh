"${PREFIX}/bin/python" -m pip install --no-deps --ignore-installed -vv .
if [ "$NEED_SCRIPTS" != yes ]; then
    rm ${SP_DIR}/anaconda_anon_usage/install.py
    exit 0
fi
mkdir -p "${PREFIX}/etc/conda/activate.d"
mkdir -p "${PREFIX}/python-scripts"
cp "scripts/post-link.sh" "${PREFIX}/etc/conda/activate.d/${PKG_NAME}_activate.sh"
cp "scripts/post-link.bat" "${PREFIX}/etc/conda/activate.d/${PKG_NAME}_activate.bat"
cp "scripts/post-link.sh" "${PREFIX}/python-scripts/.${PKG_NAME}-post-link.sh"
cp "scripts/pre-unlink.sh" "${PREFIX}/python-scripts/.${PKG_NAME}-pre-unlink.sh"
cp "scripts/post-link.bat" "${PREFIX}/python-scripts/.${PKG_NAME}-post-link.bat"
cp "scripts/pre-unlink.bat" "${PREFIX}/python-scripts/.${PKG_NAME}-pre-unlink.bat"
