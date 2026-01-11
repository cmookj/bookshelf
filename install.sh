#!/usr/bin/env bash

# Build
uv build

# Install
PREFIX=$(python3 -c 'import sys; print(sys.prefix)')
CMD=""
DST=""

if [[ "$PREFIX" == /opt/homebrew/* ]]; then
    echo "Homebrew Python"
    CMD="uv pip install dist/*.whl"
    DST="/opt/homebrew"
else
    echo "System Python"
    CMD="sudo uv pip install dist/*.whl"
    DST="/usr/local"
fi

$CMD \
--python=$(which python3) \
--prefix=$DST
