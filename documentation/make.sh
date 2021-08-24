#!/usr/bin/env bash

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd ${SCRIPT_DIR}

cd ../FireSTARR
doxygen firestarr.conf
cd ../GIS
doxygen gis.conf
cd ../WeatherSHIELD
doxygen weathershield.conf
cd ../documentation
doxygen fireguard.conf
