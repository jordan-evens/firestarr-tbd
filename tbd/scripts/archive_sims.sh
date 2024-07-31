#!/bin/bash
KEEP_UNARCHIVED=10

DIR_FROM="/appl/data/sims"
DIR_BKUP="/appl/data/sims.bkup"

# override KEEP_UNARCHIVED if set in config
. /appl/data/config || . /appl/config

function do_archive()
{
  OPTIONS="-mtm -mtc -r -mx=9 -stl"
  run="$1"
  do_delete="$2"
  file_out="${DIR_BKUP}/${run}.7z"
  # file_newest="${run}`ls -hArt ${run} | tail -n 1`"
  file_newest=`find ${run} -type f -printf '%T@ %P\n' | sort -n | tail -n1 | awk '{print $2}'`
  echo "Archiving ${run} as ${file_out}"
  if [ -f "${file_out}" ]; then
    if [ "${file_newest}" -nt "${file_out}" ]; then
      echo "Checking existing archive ${file_out}"
      # if 7z can't open the archive then we need to get rid of it
      7za t "${file_out}" || (rm "${file_out}")
    else
      echo "Archive already up-to-date"
      return
    fi
  fi
  if [ "" != "${do_delete}" ];
  then
    echo "Archiving and deleting ${run}"
    7za a ${OPTIONS} -sdel "${file_out}" "${DIR_FROM}/${run}/*" && rmdir "${DIR_FROM}/${run}"
  else
    echo "Archiving without deleting ${run}"
    if [ -f "${file_out}" ]; then
      echo "Creating ${file_out}"
      7za a ${OPTIONS} "${file_out}" "${DIR_FROM}/${run}/*"
    else
      if [ "${file_newest}" -nt "${file_out}" ]; then
        echo "Updating ${file_out}"
        # 7za u -u- -up0q0r2w2x0y2z0 ${OPTIONS} "${file_out}" "${DIR_FROM}/${run}/*"
        7za u ${OPTIONS} "${file_out}" "${DIR_FROM}/${run}/*"
      else
        echo "Archive already up-to-date"
      fi
    fi
  fi
}

pushd ${DIR_FROM}
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
