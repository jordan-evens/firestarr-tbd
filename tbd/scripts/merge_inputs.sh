#!/bin/bash

DIR_SIMS=/appl/data/sims

# # if we could get it running
# LAST_RUN=`ls -1 ${DIR_SIMS} | sort | tail -n 1`
# # need to cancel this before it runs things
# scripts/lock_run.sh --no-publish --no-merge --no-resume --no-retry
# # at this point expect to have all the sims prepared but nothing running

# scripts/force_run.sh --prepare-only --no-resume

# but for now just use the last two runs
LAST_RUN=`ls -1 ${DIR_SIMS} | sort | tail -n 2 | head -n 1`

CUR_RUN=`ls -1 ${DIR_SIMS} | sort | tail -n 1`

# see if we can match exact outputs for any folders
DIFF_RESULTS=`diff -q ${DIR_SIMS}/${LAST_RUN}/sims ${DIR_SIMS}/${CUR_RUN}/sims`
# echo ${DIFF_RESULTS} | grep "Common subdirectories" | sed "s/.*${DIR_SIMS}/${LAST_RUN}/sims/\([^ ]*\) and.*/\1/g"
# diff -q ${DIR_SIMS}/${LAST_RUN}/sims ${DIR_SIMS}/${CUR_RUN}/sims | grep "Common subdirectories" | sed "s/.*sims\/\([^ ]*\) and.*/\1/g"

echo "Merging ${LAST_RUN} into ${CUR_RUN}"
set -e

N=0
copied=0

for d in `diff -q ${DIR_SIMS}/${LAST_RUN}/sims ${DIR_SIMS}/${CUR_RUN}/sims | grep "Common subdirectories" | sed "s/.*sims\/\([^ ]*\) and.*/\1/g"`; do
    # common directories
    old="${DIR_SIMS}/${LAST_RUN}/sims/${d}"
    new="${DIR_SIMS}/${CUR_RUN}/sims/${d}"
    N=$(expr ${N} + 1)
    # check that sim conditions, input tif and weather are the same
    (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep sim.sh > /dev/null) || continue
    (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep ${d}/${d}.tif) > /dev/null || continue
    (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep ${d}/firestarr_${d}_wx.csv) > /dev/null || continue
    echo "Results for ${d} are from same inputs so copying"
    # cp -rv ${old}/* ${new}/
    rsync -avHP --exclude="*.lock" --delete ${old}/ ${new}/
    copied=$(expr ${copied} + 1)
done

echo "Copied outputs from ${copied} / ${N} directories"

# for d in `diff -q ${DIR_SIMS}/${LAST_RUN}/sims ${DIR_SIMS}/${CUR_RUN}/sims | grep "Common subdirectories" | sed "s/.*sims\/\([^ ]*\) and.*/\1/g"`; do
#     # uncommon directories - just do nothing since new run will run what it has?
#     old="${DIR_SIMS}/${LAST_RUN}/sims/${d}"
#     new="${DIR_SIMS}/${CUR_RUN}/sims/${d}"
#     # check that sim conditions, input tif and weather are the same
#     (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep sim.sh > /dev/null) || continue
#     (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep ${d}/${d}.tif) > /dev/null || continue
#     (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep ${d}/firestarr_${d}_wx.csv) > /dev/null || continue
#     echo "Results for ${d} are from same inputs so copying"
#     cp -rv ${old}/* ${new}/
# done
