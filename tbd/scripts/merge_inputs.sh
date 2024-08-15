#!/bin/bash
DIR=`dirname $(realpath "$0")`
export FORCE_RUN=1
# export IS_CRONJOB=${IS_CRONJOB}
# HACK: clear for now
export IS_CRONJOB=
# use update.sh so we can lock entire script on `/usr/bin/flock -n /appl/data/update.lock`

DIR_SIMS=/appl/data/sims
set -e

echo "Checking that previous run completed and published successfully"
# NOTE: don't use --resume because if it's old weather it needs to run from scratch
(${DIR}/update.sh --no-publish --no-merge --no-retry && ${DIR}/check_and_publish.sh) || (echo "Previous run didn't finish properly" && exit -1)

# # if we could get it running
# LAST_RUN=`ls -1 ${DIR_SIMS} | sort | tail -n 1`
# # need to cancel this before it runs things
# scripts/lock_run.sh --no-publish --no-merge --no-resume --no-retry
# # at this point expect to have all the sims prepared but nothing running

# since previous run finished fine we can do this
echo "Preparing new run to merge into"
(${DIR}/update.sh --prepare-only --no-resume --no-retry) || (echo "Couldn't create new run to merge into" && exit -1)

# but for now just use the last two runs
LAST_RUN=`ls -1 ${DIR_SIMS} | sort | tail -n 2 | head -n 1`

CUR_RUN=`ls -1 ${DIR_SIMS} | sort | tail -n 1`

# see if we can match exact outputs for any folders
DIFF_RESULTS=`diff -q ${DIR_SIMS}/${LAST_RUN} ${DIR_SIMS}/${CUR_RUN}`
# echo ${DIFF_RESULTS} | grep "Common subdirectories" | sed "s/.*${DIR_SIMS}/${LAST_RUN}/\([^ ]*\) and.*/\1/g"
# diff -q ${DIR_SIMS}/${LAST_RUN} ${DIR_SIMS}/${CUR_RUN} | grep "Common subdirectories" | sed "s/.*sims\/\([^ ]*\) and.*/\1/g"

echo "Merging ${LAST_RUN} into ${CUR_RUN}"

N=0
copied=0

# anything that's already a symlink will not show up in diff output so won't happen in this loop
for d in `diff -q ${DIR_SIMS}/${LAST_RUN} ${DIR_SIMS}/${CUR_RUN} | grep "Common subdirectories" | sed "s/.*\/\([^ ]*\) and.*/\1/g"`; do
    # common directories
    old="${DIR_SIMS}/${LAST_RUN}/${d}"
    new="${DIR_SIMS}/${CUR_RUN}/${d}"
    N=$(expr ${N} + 1)
    echo "Checking ${d}"
    if [ "$(realpath ${old})" == "$(realpath ${new})" ]; then
        # NOTE: this should never get reached but leaving it for clarity about what's going on
        echo "Results for ${d} are already reused"
    else
        # check that sim conditions, input tif and weather are the same
        # only care about simulation call line being the same so we can tweak script otherwise and still see as the same
        diff <(grep tbd ${old}/sim.sh) <(grep tbd ${new}/sim.sh) > /dev/null || continue
        (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep ${d}/${d}.tif) > /dev/null || continue
        (diff -rqs ${old} ${new} | grep -v ".lock" | grep identical | grep ${d}/firestarr_${d}_wx.csv) > /dev/null || continue
        echo "Results for ${d} are from same inputs so reusing"
        # instead of copying just use symlinks
        rm -rf ${new} && ln -s ${old} ${new}
    fi
    copied=$(expr ${copied} + 1)
done

echo "Copied outputs from ${copied} / ${N} directories"
if [ "${copied}" -eq "${N}" ]; then
    # FIX: kind of dumb to copy everything if it's the same and then delete but simpler for now
    echo "All inputs are the same so no reason to run anything or keep this version"
    echo "Deleting ${CUR_RUN}"
    rm -rfv "${DIR_SIMS}/${CUR_RUN}"
    echo "${LAST_RUN} was already up-to-date so deleted ${CUR_RUN}"
else
    echo "Running merged run in ${CUR_RUN}"
    (${DIR}/update.sh --no-publish --no-merge --no-retry) || (echo "Merged run didn't finish properly" && exit -1)
    echo "Validating merged run in ${CUR_RUN}"
    (${DIR}/update.sh --no-publish --no-merge --no-retry) || (echo "Validating merged run" && exit -1)
    echo "Publishing merged run in ${CUR_RUN}"
    (${DIR}/check_and_publish.sh) || (echo "Couldn't publish after finished" && exit -1)
fi
