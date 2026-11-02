#!/bin/bash

set -e

version=$1; shift
vflag="==$version"

SCRIPTDIR=$(cd $(dirname $BASH_SOURCE[0]) && pwd)
CONDA_PREFIX=$(cd $CONDA_PREFIX && pwd)
source $CONDA_PREFIX/*/activate
# Needed to convert windows path to unix
CONDA_PREFIX=$(cd $CONDA_PREFIX && pwd)

cat >construct.yaml <<EOD
name: AIDTest
version: 1.0
installer_type: all
channels:
  - local
  - defaults
specs:
  - conda${vflag:-}
  - anaconda-anon-usage
EOD

echo "-----"
cat construct.yaml
echo "-----"

# On win-64, openssl's bash activation script sets SSL_CERT_FILE to
# $CONDA_PREFIX/ssl/cacert.pem, but the bundle lives in Library/ssl. The
# MSI build (installer_type: all) runs briefcase, and briefcase >=0.4.7
# downloads WiX via httpx2, which honors SSL_CERT_FILE and fails with
# FileNotFoundError. Drop a value that points at a missing file.
if [[ -n "${SSL_CERT_FILE:-}" && ! -f "$SSL_CERT_FILE" ]]; then
  echo "Ignoring nonexistent SSL_CERT_FILE: $SSL_CERT_FILE"
  unset SSL_CERT_FILE
fi

constructor .

if [ -f AIDTest*.sh ]; then
  echo ".sh installer created"
elif [ -f AIDTest*.exe ]; then
  echo ".exe installer created"
else
  echo "No testable installer created"
  exit -1
fi
