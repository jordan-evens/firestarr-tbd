import sys
sys.path.append('../util')
import common
import json
import logging
import sys
import pandas as pd
import math

startup = {
            'ffmc':          {'value': 85.0},
            'dmc':           {'value': 6.0},
            'dc':            {'value': 15.0},
            'precipitation': {'value': 0.0},
          }

def unnest_values(dict):
    for i in dict:
        dict[i] = dict[i]['value']

def try_read_first(dict, key, fail_msg=None, is_fatal=False):
    result = dict[key]
    n = len(result)
    if n < 1:
        msg = "No {} provided".format(key)
        if fail_msg is not None:
            msg = "{} - {}".format(msg, fail_msg)
        if is_fatal:
            logging.fatal(msg)
            sys.exit(-1)
        logging.warning(msg)
        return None
    else:
        if len(result) > 1:
            logging.warning("{} {} provided - only the first one will be used".format(n, key))
    return result[0]

with open(sys.argv[1]) as f:
  data = json.load(f)

MSG_DEFAULT_STARTUP = 'using default startup indices'
project = data['project']
stn = try_read_first(project['stations'], 'stations', MSG_DEFAULT_STARTUP)
if stn is not None:
    stream = try_read_first(stn['station'], 'streams', MSG_DEFAULT_STARTUP)
    if stream is not None:
        startup = stream['condition']['startingCodes']
unnest_values(startup)
logging.info("Startup indices are: {}".format(startup))


pt = None
ignition = try_read_first(project['ignitions'], 'ignitions', is_fatal=True)
ign = try_read_first(ignition['ignition']['ignitions'], 'ignitions', is_fatal=True)

if ign['polyType'] != 'POINT':
    logging.fatal("Only point ignition is currently supported")
poly = ign['polygon']
if poly['units'] != 'LAT_LON':
    logging.fatal("Only lat/long coordinates are currently supported")
pt = try_read_first(poly['polygon'], 'points', is_fatal=True)

if pt is None:
    # should have already exited but check
    logging.fatal("Ignition point not initialized")
unnest_values(pt)
logging.info("Startup coordinates are {}".format(pt))


scenario = try_read_first(project['scenarios'], 'scenarios', is_fatal=True)['scenario']
start_time = scenario['startTime']['time']
start_time = pd.to_datetime(start_time)
logging.info("Scenario start time is: {}".format(start_time))


tz = (start_time.tz._minutes) / 60.0
if math.floor(tz) != tz:
    logging.fatal("Currently not set up to deal with partial hour timezones")
    sys.exit(-1)
logging.info("Timezone offset is {}".format(tz))


#http:/wxshield:80/wxshield/getWx.php?model=geps&lat=46&long=-95&dateOffset=0&tz=-5&mode=daily
