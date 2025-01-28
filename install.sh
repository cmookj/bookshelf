#!/usr/bin/env bash

DST=~/.local/share/bin
mkdir -p ${DST}

ln -s $(pwd)/bookshelf.py ${DST}/bookshelf
