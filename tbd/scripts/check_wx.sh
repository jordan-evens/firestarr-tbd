#!/bin/bash
. /appl/data/config || . /appl/config

if [ -z "${SPOTWX_API_KEY}" ] \
    || [ -z "${BOUNDS_LATITUDE_MAX}" ] \
    || [ -z "${BOUNDS_LATITUDE_MIN}" ] \
    || [ -z "${BOUNDS_LONGITUDE_MAX}" ] \
    || [ -z "${BOUNDS_LONGITUDE_MIN}" ] \
    ; then
    echo SPOTWX_API_KEY must be set
else
    LATITUDE=$((${BOUNDS_LATITUDE_MAX} - ${BOUNDS_LATITUDE_MIN}))
    LONGITUDE=$((${BOUNDS_LONGITUDE_MAX} - ${BOUNDS_LONGITUDE_MIN}))
    MODEL=geps
    URL_TEST="https://spotwx.io/api.php?key=${SPOTWX_API_KEY}&lat=${LATITUDE}&lon=${LONGITUDE}&model=${MODEL}&output=archive"
    DIR=/appl/data
    CURDATE=`date -u --rfc-3339=seconds`

    source /appl/.venv/bin/activate || echo No venv
    curl -sk "${URL_TEST}"
fi
