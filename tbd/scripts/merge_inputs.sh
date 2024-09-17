#!/bin/bash
DIR=`dirname $(realpath "$0")`
export FORCE_RUN=1
# export IS_CRONJOB=${IS_CRONJOB}
# HACK: clear for now
export IS_CRONJOB=
# use update.sh so we can lock entire script on `/usr/bin/flock -n /appl/data/update.lock`

DIR_SIMS="/appl/data/sims"
DIR_RUNS="/appl/data/runs"
SUBDIR_COMMON="current"
set -e

echo "Checking that previous run completed and published successfully"
# NOTE: don't use --resume because if it's old weather it needs to run from scratch
(${DIR}/update.sh --no-publish --no-merge --no-retry && ${DIR}/check_and_publish.sh) || (echo "Previous run didn't finish properly" && exit -1)

LAST_RUN=`ls -1 ${DIR_SIMS} | sort | grep -v "${SUBDIR_COMMON}" | tail -n 1`
dir_last_sims="${DIR_SIMS}/${LAST_RUN}"
dir_last_runs="${DIR_RUNS}/${LAST_RUN}"

# couldn't we just point the whole "current" directory at the latest run?
# # use symlinks to last run if folders for "current" don't exist yet
# if [ ! -d "${DIR_RUNS}/${SUBDIR_COMMON}" ]; then
#     mkdir -p "${DIR_RUNS}/${SUBDIR_COMMON}"
#     ls -1 ${dir_last_runs} | grep -v ".log" | xargs -tI {} ln -s "${dir_last_runs}/{}" "${DIR_RUNS}/${SUBDIR_COMMON}/{}"
# fi
# if [ ! -d "${DIR_SIMS}/${SUBDIR_COMMON}" ]; then
#     # should point at all folders in last run
#     mkdir -p "${DIR_SIMS}/${SUBDIR_COMMON}"
#     ls -1 ${dir_last_sims} | xargs -tI {} ln -s "${dir_last_sims}/{}" "${DIR_SIMS}/${SUBDIR_COMMON}/{}"
# fi


# # if we could get it running
# LAST_RUN=`ls -1 ${DIR_SIMS} | sort | tail -n 1`
# # need to cancel this before it runs things
# scripts/lock_run.sh --no-publish --no-merge --no-resume --no-retry
# # at this point expect to have all the sims prepared but nothing running

# since previous run finished fine we can do this
echo "Preparing new run to merge into"
(${DIR}/update.sh --prepare-only --no-resume --no-retry) || (echo "Couldn't create new run to merge into" && exit -1)

# same as above since we just added another directory to the end of the list
CUR_RUN=`ls -1 ${DIR_SIMS} | sort | grep -v "${SUBDIR_COMMON}" | tail -n 1`
dir_cur_sims="${DIR_SIMS}/${CUR_RUN}"
dir_cur_runs="${DIR_RUNS}/${CUR_RUN}"

echo "Merging ${LAST_RUN} into ${CUR_RUN}"

N=0
copied=0

# anything that's already a symlink will not show up in diff output so won't happen in this loop
for d in `diff -q ${dir_last_sims} ${dir_cur_sims} | grep -v "model" | grep "Common subdirectories" | sed "s/.*\/\([^ ]*\) and.*/\1/g"`; do
    # common directories
    old="${dir_last_sims}/${d}"
    new="${dir_cur_sims}/${d}"
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
        # NOTE: could use links that point forward in time so when things get archived links are still valid
        #       but if we keep all the archives for today at least then we should be able to point backward
        #       to avoid moving and copying things so much
        # # move previous results into this run
        # rm -rf ${new} && mv ${old} ${new} && ln -s ${new} ${old}
        # symlink to old run from new
        # use relative symlink so path should be good in azure still
        rm -rf ${new} && ln -s `realpath ${old} --relative-to=${dir_cur_sims}` ${new}
    fi
    copied=$(expr ${copied} + 1)
done

echo "Copied outputs from ${copied} / ${N} directories"
if [ "${copied}" -eq "${N}" ]; then
    # FIX: kind of dumb to copy everything if it's the same and then delete but simpler for now
    echo "All inputs are the same so no reason to run anything or keep this version"
    echo "Deleting ${CUR_RUN}"
    rm -rfv "${dir_cur_sims}"
    echo "${LAST_RUN} was already up-to-date so deleted ${CUR_RUN}"
else
    echo "Running merged run in ${CUR_RUN}"
    # update symlinks for current folders
    dir_common_sims="${DIR_SIMS}/${SUBDIR_COMMON}"
    dir_common_runs="${DIR_RUNS}/${SUBDIR_COMMON}"
    ln -sfn "`realpath ${dir_cur_sims} --relative-to=${DIR_SIMS}`" "${dir_common_sims}"
    ln -sfn "`realpath ${dir_cur_runs} --relative-to=${DIR_RUNS}`" "${dir_common_runs}"
    # if we call pointing at current directory it should make tasks there instead of using actual folder name
    (${DIR}/update.sh --no-publish --no-merge --no-retry "${dir_common_runs}") || (echo "Merged run didn't finish properly" && exit -1)
    # echo "Validating merged run in ${CUR_RUN}"
    # (${DIR}/update.sh --no-publish --no-merge --no-retry) || (echo "Validating merged run" && exit -1)
    # echo "Publishing merged run in ${CUR_RUN}"
    # (${DIR}/check_and_publish.sh) || (echo "Couldn't publish after finished" && exit -1)
fi
