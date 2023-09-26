#!/bin/bash
echo `date -u --rfc-3339=seconds`: Running check and publish >> /appl/data/logs/check_and_publish.log
. /appl/data/config || . /appl/config
source /appl/.venv/bin/activate || echo No venv
python /appl/tbd/src/py/firestarr/check_and_publish.py $* || (echo FAILED >> /appl/data/logs/check_and_publish.log)
echo `date -u --rfc-3339=seconds`: Done running check and publish >> /appl/data/logs/check_and_publish.log
