#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd ${SCRIPT_DIR}

cd ../TBD
doxygen tbd.conf
cd ../GIS
doxygen gis.conf
cd ../documentation
doxygen main.conf
