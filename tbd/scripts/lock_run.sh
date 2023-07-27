#!/bin/bash
/usr/bin/flock -n /tmp/update.lockfile /appl/tbd/src/py/firestarr/main.py $*
