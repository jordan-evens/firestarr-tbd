import sys
sys.path.append('../util')
import common
import json
import logging
import sys

startup = {
            'ffmc':          {'value': 85.0},
            'dmc':           {'value': 6.0},
            'dc':            {'value': 15.0},
            'precipitation': {'value': 0.0},
          }

def unnest_values(dict):
    for i in dict:
        dict[i] = dict[i]['value']

#wget -O wx.csv 'http://wxshield:80/wxshield/getWx.php?lat=46&long=-95&dateOffset=0&numDays=300&model=geps'

with open(sys.argv[1]) as f:
  data = json.load(f)

project = data['project']
stns = project['stations']['stations']
if len(stns) < 1:
    logging.warning("No stations provided - using default startup indices")
else:
    if len(stns) > 1:
        logging.warning("{} stations provided - only the first one will be used".format(len(stns)))
    stn = stns[0]['station']
    streams = stn['streams']
    if len(streams) < 1:
        logging.warning("No streams provided - using default startup indices")
    else:
        if len(streams) > 1:
            logging.warning("{} streams provided - only the first one will be used for startup indices".format(len(streams)))
        startup = streams[0]['condition']['startingCodes']
unnest_values(startup)


pt = None
ignitions = project['ignitions']['ignitions']
if len(ignitions) < 1:
    logging.fatal("No ignitions provided")
else:
    if len(ignitions) > 1:
        logging.warning("{} ignitions provided - only the first one will be used".format(len(ignitions)))
    ignition = ignitions[0]['ignition']
    igns = ignition['ignitions']['ignitions']
    if len(igns) < 1:
        logging.fatal("No ignitions provided")
    else:
        if len(igns) > 1:
            logging.warning("{} ignitions provided - only the first one will be used".format(len(igns)))
        ign = igns[0]
        if ign['polyType'] != 'POINT':
            logging.fatal("Only point ignition is currently supported")
        poly = ign['polygon']
        if poly['units'] != 'LAT_LON':
            logging.fatal("Only lat/long coordinates are currently supported")
        pts = poly['polygon']['points']
        if len(pts) < 1:
            logging.fatal("No ignition points provided")
        else:
            if len(igns) > 1:
                logging.warning("{} ignition points provided - only the first one will be used".format(len(pts)))
            pt = pts[0]

if pt is None:
    # should have already exited but check
    logging.fatal("Ignition point not initialized")
unnest_values(pt)

logging.info("Startup coordinates are {}".format(pt))
logging.info("Startup indices are: {}".format(startup))

