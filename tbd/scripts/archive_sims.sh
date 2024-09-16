#!/bin/bash
KEEP_UNARCHIVED=10

# NOTE: this merges sims and runs directories for this run into root of archive
DIR_FROM_SIMS="/appl/data/sims"
DIR_FROM_RUNS="/appl/data/runs"
DIR_BKUP="/appl/data/sims.bkup"

# override KEEP_UNARCHIVED if set in config
. /appl/data/config || . /appl/config

function do_archive()
{
  run="$1"
  do_delete="$2"
  # # update without existing file is the same as 'a'
  # zip_type="u"
  # '-sdel' doesn't work with 'u'
  zip_type="a"
  options="-mtm -mtc -mx=9 -stl"
  file_out="${DIR_BKUP}/${run}.7z"
  dir_sims="${DIR_FROM_SIMS}/${run}"
  dir_runs="${DIR_FROM_RUNS}/${run}"
  if [ "" != "${do_delete}" ]; then
    echo "Archiving and deleting ${run}"
    options="${options} -sdel"
  else
    echo "Archiving without deleting ${run}"
    file_newest=`(find ${dir_sims} -type f -printf '%T@ %P\n'; find ${dir_runs} -type f -printf '%T@ %P\n')  | sort -n | tail -n1 | awk '{print $2}'`
    echo "Archiving ${run} as ${file_out}"
    if [ -f "${file_out}" ]; then
      echo "Updating ${file_out}"
      if [ "${file_newest}" -nt "${file_out}" ]; then
        echo "Checking existing archive ${file_out}"
        # if 7z can't open the archive then we need to get rid of it
        7za t "${file_out}" || (rm "${file_out}")
      else
        echo "Archive already up-to-date"
        return
      fi
    else
      echo "Creating ${file_out}"
    fi
  fi
  if [ -d "${dir_sims}" ]; then
    echo "Adding ${dir_sims}"
    7za ${zip_type} ${options} "${file_out}" "${dir_sims}/*" \
      && rmdir --ignore-fail-on-non-empty "${dir_sims}"
  fi
  if [ -d "${dir_runs}" ]; then
    echo "Adding ${dir_runs}"
    7za ${zip_type} ${options} "${file_out}" "${dir_runs}/*" \
      && rmdir --ignore-fail-on-non-empty "${dir_runs}"
  fi
}

pushd ${DIR_FROM_RUNS}
mkdir -p ${DIR_BKUP}
rmdir * > /dev/null 2>&1
set -e
for run in `ls -1 | head -n-${KEEP_UNARCHIVED}`
do
  do_archive "${run}" 1
done

# do for everything after doing things that can be deleted
for run in `ls -1`
do
  do_archive "${run}"
done

popd
