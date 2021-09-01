import sys
sys.path.append('../util')
import common
import json
import logging
import sys
import pandas as pd
import math
import datetime
import shlex
import timeit
from osgeo import ogr
from osgeo import osr
import statistics
import fiona
from shapely.geometry import Polygon, mapping
import os
import firestarr_gis
import numpy as np

DATA_DIR = common.ensure_dir('/FireGUARD/data')
ROOT_DIR = common.ensure_dir(os.path.join(DATA_DIR, 'sims'))
OUTPUT_DIR = common.ensure_dir(os.path.join(DATA_DIR, 'output'))
PERIM_DIR = common.ensure_dir(os.path.join(OUTPUT_DIR, 'perimeter'))
PROB_DIR = common.ensure_dir(os.path.join(OUTPUT_DIR, 'probability'))

def unnest_values(dict):
    for i in dict:
        dict[i] = dict[i]['value']
    return dict

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

def do_run(fgmj):
    startup = {
                'ffmc':          {'value': 85.0},
                'dmc':           {'value': 6.0},
                'dc':            {'value': 15.0},
                'precipitation': {'value': 0.0},
              }
    region = os.path.basename(os.path.dirname(os.path.dirname(fgmj)))
    job_name = os.path.basename(os.path.dirname(fgmj))
    job_time = job_name[job_name.rindex('_') + 1:-4]
    job_date = job_time[:8]
    fire_name = job_name[:job_name.index('_')]
    out_dir = os.path.join(ROOT_DIR, job_date, region, fire_name, job_time)
    done_already = os.path.exists(out_dir)
    if done_already:
        print("Already done")
    else:
        common.ensure_dir(out_dir)
        with open(fgmj) as f:
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
        ffmc = startup['ffmc']
        dmc = startup['dmc']
        dc = startup['dc']
        apcp_0800 = float(startup['precipitation'])
        if np.isnan(apcp_0800):
            apcp_0800 = 0
        pt = None
        ignition = try_read_first(project['ignitions'], 'ignitions', is_fatal=True)
        ign = try_read_first(ignition['ignition']['ignitions'], 'ignitions', is_fatal=True)
        perim = None
        poly = ign['polygon']
        if poly['units'] != 'LAT_LON':
            logging.fatal("Only lat/long coordinates are currently supported")
            sys.exit(-1)
        if ign['polyType'] != 'POINT':
            logging.fatal("Only point ignition is currently supported")
            if ign['polyType'] == 'POLYGON_OUT':
                pts = poly['polygon']['points']
                pts = list(map(unnest_values, pts))
                pts = [list(map(lambda v: [v['x'], v['y']], pts))]
                lat = statistics.mean(list(map(lambda v: v[1], pts[0])))
                long = statistics.mean(list(map(lambda v: v[0], pts[0])))
                print(long)
                orig_zone = 15
                orig_long = -93
                diff = long - orig_long
                print(diff)
                ZONE_SIZE = 6
                zone_diff = round(diff / ZONE_SIZE)
                print(zone_diff)
                meridian = orig_long + (zone_diff * ZONE_SIZE)
                print(meridian)
                zone = orig_zone + zone_diff
                # print(pts)
                p = '''{"type": "Polygon",
                        "coordinates": ''' + str(pts) + ''',
                    }'''
                # print(p)
                g = ogr.CreateGeometryFromJson(p)
                # print(g)
                # print("Hi! I'm a %s with an Area  %s" % (g.GetGeometryName(), g.Area()))
                # print("I have inside me %s feature(s)!\n" % g.GetGeometryCount())
                # for idx, f in enumerate(g):
                    # print("I'm feature n.%s and I am a %s.\t I have an Area of %s - You can get my json repr with f.ExportToJson()" % (idx, f.GetGeometryName(),f.Area()))
                source = osr.SpatialReference()
                source.ImportFromEPSG(4269)
                target = osr.SpatialReference()
                target.ImportFromEPSG(3159)
                z = target.ExportToWkt()
                z = z[:z.rindex(",AUTHORITY")] + "]"
                z = z.replace('UTM zone 15N', 'UTM zone {}N')
                z = z.replace('"central_meridian",-93', '"central_meridian",{}')
                z = z.format(zone, meridian)
                print(z)
                print(target)
                target.ImportFromWkt(z)
                transform = osr.CoordinateTransformation(source, target)
                g.Transform(transform)
                print(g)
                print("Hi! I'm a %s with an Area  %s" % (g.GetGeometryName(), g.Area()))
                print("I have inside me %s feature(s)!\n" % g.GetGeometryCount())
                for idx, f in enumerate(g):
                    print("I'm feature n.%s and I am a %s.\t I have an Area of %s - You can get my json repr with f.ExportToJson()" % (idx, f.GetGeometryName(),f.Area()))
                out_name = '{}.shp'.format(fire_name)
                out_file = os.path.join(out_dir, out_name)
                driver = ogr.GetDriverByName("Esri Shapefile")
                ds = driver.CreateDataSource(out_file)
                layr1 = ds.CreateLayer('', None, ogr.wkbPolygon)
                # create the field
                layr1.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
                # Create the feature and set values
                defn = layr1.GetLayerDefn()
                feat = ogr.Feature(defn)
                feat.SetField('id', 1)
                feat.SetGeometry(g)
                layr1.CreateFeature(feat)
                # close the shapefile
                ds.Destroy()
                target.MorphToESRI()
                with open(os.path.join(out_dir, '{}.prj'.format(fire_name)), 'w') as file:
                    file.write(target.ExportToWkt())
                YEAR = 2021
                perim = firestarr_gis.rasterize_perim(out_dir, out_file, YEAR, fire_name)[1]
            if perim is None:
                sys.exit(-1)
        else:
            pt = try_read_first(poly['polygon'], 'points', is_fatal=True)
            if pt is None:
                # should have already exited but check
                logging.fatal("Ignition point not initialized")
                sys.exit(-1)
            unnest_values(pt)
            lat = pt['y']
            long = pt['x']
        logging.info("Startup coordinates are {}, {}".format(lat, long))
        scenario = try_read_first(project['scenarios'], 'scenarios', is_fatal=True)['scenario']
        start_time = scenario['startTime']['time']
        start_time = pd.to_datetime(start_time)
        logging.info("Scenario start time is: {}".format(start_time))
        hour = start_time.hour
        minute = start_time.minute
        tz = (start_time.tz._minutes) / 60.0
        if math.floor(tz) != tz:
            logging.fatal("Currently not set up to deal with partial hour timezones")
            sys.exit(-1)
        tz = int(tz)
        logging.info("Timezone offset is {}".format(tz))
        date_offset = 0
        start_date = datetime.date.today()
        start_date = start_time.date()
        if start_date != datetime.date.today():
            date_offset = (start_date - datetime.date.today()).days
            logging.warning("Simulation does not start today - date offset set to {}".format(date_offset))
        url = r"http://wxshield:80/wxshield/getWx.php?model=geps&lat={}&long={}&dateOffset={}&tz={}&mode=daily".format(lat, long, date_offset, tz)
        logging.debug(url)
        try:
            csv = common.download(url).decode("utf-8")
        except:
            logging.fatal("Unable to download weather")
            sys.exit(-3)
        data = [x.split(',') for x in csv.splitlines()]
        df = pd.DataFrame(data[1:], columns=data[0])
        print(df)
        # supposed to be really picky about inputs
        #"Scenario,Date,APCP,TMP,RH,WS,WD,FFMC,DMC,DC,ISI,BUI,FWI";
        df = df[['MEMBER', 'DAILY', 'PREC', 'TEMP', 'RH', 'WS', 'WD']]
        df.columns = ['Scenario', 'Date', 'APCP', 'TMP', 'RH', 'WS', 'WD']
        # for some reason scenario numbers are negative right now?
        df['Scenario'] = df['Scenario'].apply(lambda x: -1 - int(x))
        df['Date'] = df['Date'].apply(lambda x: x + " 13:00:00")
        for col in ['FFMC', 'DMC', 'DC', 'ISI', 'BUI', 'FWI']:
            df[col] = 0
        df.to_csv('wx.csv', index=False)
        cmd = "./FireSTARR"
        args = "{} {} {} {} {}:{:02d} -v --wx wx.csv --ffmc {} --dmc {} --dc {} --apcp_0800 {}".format(out_dir, start_date, lat, long, hour, minute, ffmc, dmc, dc, apcp_0800)
        if perim is not None:
            args = args + " --perim {}".format(perim)
        # run generated command for parsing data
        run_what = [cmd] + shlex.split(args.replace('\\', '/'))
        logging.info("Running: " + ' '.join(run_what))
        t0 = timeit.default_timer()
        stdout, stderr = common.finish_process(common.start_process(run_what, "/FireGUARD/FireSTARR"))
        t1 = timeit.default_timer()
        logging.info("Took {}s to run simulations".format(t1 - t0))
        log_name = os.path.join(out_dir, "log.txt")
        with open(log_name, 'w') as log_file:
            log_file.write(stdout.decode('utf-8'))
    outputs = sorted(os.listdir(out_dir))
    perims = [x for x in outputs if x.endswith('tif')]
    if len(perims) > 0:
        perim = perims[0]
        firestarr_gis.project_raster(os.path.join(out_dir, perim),
                                     os.path.join(PERIM_DIR, job_date, region, fire_name + '.tif'),
                                     options=['COMPRESS=LZW', 'TILED=YES'])
    probs = [x for x in outputs if x.endswith('asc') and x.startswith('wxshield')]
    if len(probs) > 0:
        prob = probs[-1]
        firestarr_gis.project_raster(os.path.join(out_dir, prob), os.path.join(PROB_DIR, job_date, region, fire_name + '.tif'))
    if done_already:
        return None
    return log_name


if __name__ == "__main__":
    do_run(sys.argv[1])
