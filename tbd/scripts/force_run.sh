#!/bin/bash
DIR=`dirname $(realpath "$0")`
export FORCE_RUN=1
/usr/bin/flock -n /appl/data/update.lock ${DIR}/update.sh $*
