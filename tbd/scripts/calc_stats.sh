#!/bin/bash
DIR=`dirname $(realpath "$0")`
RUN_ID=`pwd | sed "s/.*\/\(.*\)/\1/g"`
DIR_TMP=/tmp
PREFIX="${DIR_TMP}/${RUN_ID}"
FILE_GROUPS="${PREFIX}_files.txt"
FILE_TIMES="${PREFIX}_times.txt"
FILE_SIMS="${PREFIX}_sims.txt"
FILE_STATS="${RUN_ID}_stats.csv"
find -type f -name log.txt | sed "s/.\/\([^/\]*\)\/.*/\1/g" > "${FILE_GROUPS}"
${DIR}/calc_all_times.sh > "${FILE_TIMES}"
${DIR}/calc_count_sims.sh > "${FILE_SIMS}"
echo group,seconds,simulations > "${FILE_STATS}"
paste "${FILE_GROUPS}" "${FILE_TIMES}" "${FILE_SIMS}" -d "," >> "${FILE_STATS}"
