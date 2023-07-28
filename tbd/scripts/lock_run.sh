#!/bin/bash
/usr/bin/flock -n /tmp/update.lockfile python /appl/tbd/src/py/firestarr/main.py $*
