#!/bin/bash
DIR=`dirname $(realpath "$0")`
# find -type f -name log.txt | xargs -I {} grep -il cancelled {} | xargs -I {} ${DIR}/calc_time.sh {}
find -type f -name log.txt | sort | xargs -I {} ${DIR}/calc_time.sh {}
