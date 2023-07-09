#!/bin/bash
# DIR=`dirname $(realpath "$0")`
# # find -type f -name log.txt | xargs -I {} grep -il cancelled {} | xargs -I {} ${DIR}/calc_time.sh {}
# find -type f -name log.txt | xargs -I {} grep -Li "Fire size at end of day 1" {} | xargs -I {} ${DIR}/calc_time.sh {}
# instead of looking at logs, look at process times
# 1     get all processes
# 2     match name of simulation process
# 3     match simulation directory
# 4     get start time column
# 5     convert start time to seconds
# 6     subtract seconds from current time
# SIM_DIR=$(pwd | sed "s/.*\/\(.*\)/\1/g")
SIM_DIR=data/sims
ps aux | grep tbd | grep ${SIM_DIR} | grep -v grep | awk '{print $9}' | xargs -I {} date --date="{}" '+%s' | xargs -I time expr $(date '+%s') - time
