#!/bin/bash
# DIR=`dirname $(realpath "$0")`
# instead of looking at logs, look at process times
# 1     get all processes
# 2     match name of simulation process
# 3     match simulation directory
# 4     don't match other grep processes
# 5     get start time column
# 6     convert start time to seconds
# 7     subtract seconds from current time
# SIM_DIR=$(pwd | sed "s/.*\/\(.*\)/\1/g")
SIM_DIR=data/sims
ps aux | grep tbd | grep ${SIM_DIR} | grep -v grep | awk '{print $9}' | xargs -I {} date --date="{}" '+%s' | xargs -I time expr $(date '+%s') - time
