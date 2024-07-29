#!/bin/bash
KEEP_UNARCHIVED=10

DIR_FROM="/appl/data/sims"
DIR_BKUP="/appl/data/sims.bkup"

# override KEEP_UNARCHIVED if set in config
. /appl/data/config || . /appl/config

function do_archive()
{
  run="$1"
  file_out="${DIR_BKUP}/${run}.7z"
  echo "Archiving ${run}"
  if [ -f "${file_out}" ]; then
    echo "Checking existing archive ${file_out}"
    # if 7z can't open the archive then we need to get rid of it
    7za t "${file_out}" || (rm "${file_out}")
  fi
  7za a -mx=9 -r -sdel "${file_out}" "${DIR_FROM}/${run}/*" && rmdir "${DIR_FROM}/${run}"
}

pushd ${DIR_FROM}
mkdir -p ${DIR_BKUP}
rmdir * > /dev/null 2>&1
set -e
for run in `ls -1 | head -n-${KEEP_UNARCHIVED}`
do
  do_archive "${run}"
done

popd
