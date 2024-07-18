#!/bin/bash
DIR=/appl/tbd
pushd ${DIR}
echo `date -u --rfc-3339=seconds`: Running check and publish
. /appl/data/config || . /appl/config
source /appl/.venv/bin/activate || echo No venv
# HACK: use python3 and not python so killall doesn't affect this
/usr/bin/flock -n --verbose /appl/data/publish.lock python3 ${DIR}/src/py/firestarr/check_and_publish.py $* || (echo FAILED)
echo `date -u --rfc-3339=seconds`: Done running check and publish
popd
