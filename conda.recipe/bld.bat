echo on
setlocal EnableDelayedExpansion
%PREFIX%\python.exe -m pip install --no-deps --ignore-installed -vv .
if "%NEED_SCRIPTS%" neq "yes" del %SP_DIR%\anaconda_anon_usage\install.py
if "%NEED_SCRIPTS%" neq "yes" exit
if not exist %PREFIX%\etc\conda\activate.d mkdir %PREFIX%\etc\conda\activate.d
if not exist %PREFIX%\python-scripts mkdir %PREFIX%\python-scripts
copy scripts\post-link.sh   %PREFIX%\etc\conda\activate.d\%PKG_NAME%_activate.sh
copy scripts\post-link.bat  %PREFIX%\etc\conda\activate.d\%PKG_NAME%_activate.bat
copy scripts\post-link.sh   %PREFIX%\python-scripts\.%PKG_NAME%-post-link.sh
copy scripts\pre-unlink.sh  %PREFIX%\python-scripts\.%PKG_NAME%-pre-unlink.sh
copy scripts\post-link.bat  %PREFIX%\python-scripts\.%PKG_NAME%-post-link.bat
copy scripts\pre-unlink.bat %PREFIX%\python-scripts\.%PKG_NAME%-pre-unlink.bat
