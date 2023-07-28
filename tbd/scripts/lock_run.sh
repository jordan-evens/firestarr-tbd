#!/bin/bash
/usr/bin/flock -n /appl/data/update.lock python /appl/tbd/src/py/firestarr/main.py $*
