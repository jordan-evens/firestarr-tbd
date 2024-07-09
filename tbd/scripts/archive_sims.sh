#!/bin/bash

KEEP=10

pushd /appl/data/sims
mkdir -p ../sims.bkup
rmdir * > /dev/null 2>&1
ls -1 | head -n-${KEEP} | xargs -I {} bash -c "7za a -mx=9 -r -sdel ../sims.bkup/{}.7z {}/* && rmdir {}"
popd
