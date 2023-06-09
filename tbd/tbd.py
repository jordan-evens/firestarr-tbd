import sys
sys.path.append('../util')
import common
import json
import logging
import sys
import pandas as pd
import geopandas as gpd
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
import gis
import numpy as np
import shutil

DATA_DIR = common.ensure_dir('/appl/data')
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

# def do_run(fgmj):
#     startup = {
#                 'ffmc':          {'value': 85.0},
#                 'dmc':           {'value': 6.0},
#                 'dc':            {'value': 15.0},
#                 'precipitation': {'value': 0.0},
#               }
#     with open(fgmj) as f:
#       data = json.load(f)
#     wx_stream = data['project']['stations']['stations'][0]['station']['streams'][0]
#     # startup = wx_stream['condition']['startingCodes']
#     wx_file = wx_stream['condition']['filename']
#     region = os.path.basename(os.path.dirname(os.path.dirname(fgmj)))
#     job_name = os.path.basename(os.path.dirname(fgmj))
#     job_time = job_name[job_name.rindex('_') + 1:]
#     job_date = job_time[:8]
#     scenario_name = data['project']['scenarios']['scenarios'][0]['name']
#     fire_name = scenario_name[:scenario_name.index(' ')]
#     out_dir = os.path.join(ROOT_DIR, job_date, region, fire_name, job_time)
#     done_already = os.path.exists(out_dir)
#     if not done_already:
#         common.ensure_dir(out_dir)
#         MSG_DEFAULT_STARTUP = 'using default startup indices'
#         project = data['project']
#         stn = try_read_first(project['stations'], 'stations', MSG_DEFAULT_STARTUP)
#         if stn is not None:
#             stream = try_read_first(stn['station'], 'streams', MSG_DEFAULT_STARTUP)
#             if stream is not None:
#                 startup = stream['condition']['startingCodes']
#         unnest_values(startup)
#         logging.info("Startup indices are: {}".format(startup))
#         ffmc = startup['ffmc']
#         dmc = startup['dmc']
#         dc = startup['dc']
#         apcp_0800 = float(startup['precipitation'])
#         if np.isnan(apcp_0800):
#             apcp_0800 = 0
#         pt = None
#         ignition = try_read_first(project['ignitions'], 'ignitions', is_fatal=True)
#         ign = try_read_first(ignition['ignition']['ignitions'], 'ignitions', is_fatal=True)
#         perim = None
#         poly = ign['polygon']
#         if poly['units'] != 'LAT_LON':
#             logging.fatal("Only lat/long coordinates are currently supported")
#             sys.exit(-1)
#         if ign['polyType'] != 'POINT':
#             if ign['polyType'] == 'POLYGON_OUT':
#                 pts = poly['polygon']['points']
#                 pts = list(map(unnest_values, pts))
#                 pts = [list(map(lambda v: [v['x'], v['y']], pts))]
#                 lat = statistics.mean(list(map(lambda v: v[1], pts[0])))
#                 long = statistics.mean(list(map(lambda v: v[0], pts[0])))
#                 # print(long)
#                 orig_zone = 15
#                 orig_long = -93
#                 diff = long - orig_long
#                 # print(diff)
#                 ZONE_SIZE = 6
#                 zone_diff = round(diff / ZONE_SIZE)
#                 # print(zone_diff)
#                 meridian = orig_long + (zone_diff * ZONE_SIZE)
#                 # print(meridian)
#                 zone = orig_zone + zone_diff
#                 # print(pts)
#                 p = '''{"type": "Polygon",
#                         "coordinates": ''' + str(pts) + ''',
#                     }'''
#                 # print(p)
#                 g = ogr.CreateGeometryFromJson(p)
#                 # print(g)
#                 # print("Hi! I'm a %s with an Area  %s" % (g.GetGeometryName(), g.Area()))
#                 # print("I have inside me %s feature(s)!\n" % g.GetGeometryCount())
#                 # for idx, f in enumerate(g):
#                     # print("I'm feature n.%s and I am a %s.\t I have an Area of %s - You can get my json repr with f.ExportToJson()" % (idx, f.GetGeometryName(),f.Area()))
#                 source = osr.SpatialReference()
#                 source.ImportFromEPSG(4269)
#                 target = osr.SpatialReference()
#                 target.ImportFromEPSG(3159)
#                 z = target.ExportToWkt()
#                 z = z[:z.rindex(",AUTHORITY")] + "]"
#                 z = z.replace('UTM zone 15N', 'UTM zone {}N')
#                 z = z.replace('"central_meridian",-93', '"central_meridian",{}')
#                 z = z.format(zone, meridian)
#                 # print(z)
#                 # print(target)
#                 target.ImportFromWkt(z)
#                 transform = osr.CoordinateTransformation(source, target)
#                 g.Transform(transform)
#                 #print(g)
#                 # logging.debug("Hi! I'm a %s with an Area  %s" % (g.GetGeometryName(), g.Area()))
#                 # logging.debug("I have inside me %s feature(s)!\n" % g.GetGeometryCount())
#                 # for idx, f in enumerate(g):
#                     # logging.debug("I'm feature n.%s and I am a %s.\t I have an Area of %s - You can get my json repr with f.ExportToJson()" % (idx, f.GetGeometryName(),f.Area()))
#                 out_name = '{}.shp'.format(fire_name)
#                 out_file = os.path.join(out_dir, out_name)
#                 driver = ogr.GetDriverByName("Esri Shapefile")
#                 ds = driver.CreateDataSource(out_file)
#                 layr1 = ds.CreateLayer('', None, ogr.wkbPolygon)
#                 # create the field
#                 layr1.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
#                 # Create the feature and set values
#                 defn = layr1.GetLayerDefn()
#                 feat = ogr.Feature(defn)
#                 feat.SetField('id', 1)
#                 feat.SetGeometry(g)
#                 layr1.CreateFeature(feat)
#                 # close the shapefile
#                 ds.Destroy()
#                 target.MorphToESRI()
#                 with open(os.path.join(out_dir, '{}.prj'.format(fire_name)), 'w') as file:
#                     file.write(target.ExportToWkt())
#                 YEAR = 2021
#                 perim = gis.rasterize_perim(out_dir, out_file, YEAR, fire_name)[1]
#             else:
#                 logging.fatal("Unsupported ignition type {}".format(ign['polyType']))
#             if perim is None:
#                 sys.exit(-1)
#         else:
#             pt = try_read_first(poly['polygon'], 'points', is_fatal=True)
#             if pt is None:
#                 # should have already exited but check
#                 logging.fatal("Ignition point not initialized")
#                 sys.exit(-1)
#             unnest_values(pt)
#             lat = pt['y']
#             long = pt['x']
#         logging.info("Startup coordinates are {}, {}".format(lat, long))
#         scenario = try_read_first(project['scenarios'], 'scenarios', is_fatal=True)['scenario']
#         start_time = scenario['startTime']['time']
#         start_time = pd.to_datetime(start_time)
#         logging.info("Scenario start time is: {}".format(start_time))
#         hour = start_time.hour
#         minute = start_time.minute
#         tz = (start_time.tz._minutes) / 60.0
#         if math.floor(tz) != tz:
#             logging.fatal("Currently not set up to deal with partial hour timezones")
#             sys.exit(-1)
#         tz = int(tz)
#         logging.info("Timezone offset is {}".format(tz))
#         date_offset = 0
#         start_date = datetime.date.today()
#         start_date = start_time.date()
#         if start_date != datetime.date.today():
#             date_offset = (start_date - datetime.date.today()).days
#             logging.warning("Simulation does not start today - date offset set to {}".format(date_offset))
#         with open(os.path.join(os.path.dirname(fgmj), wx_file)) as f:
#             csv = f.readlines()
#         data = [x.replace(' ', '').replace('\n', '').split(',') for x in csv]
#         df = pd.DataFrame(data[1:], columns=data[0])
#         df = df.astype({'HOUR': 'int32', 'TEMP': 'float', 'RH': 'int32', 'WD': 'int32', 'WS': 'float', 'PRECIP': 'float'})
#         df['DATE'] = df.apply(lambda x: pd.to_datetime(x['HOURLY']), axis=1)
#         df['FOR_DATE'] = df.apply(lambda x: x['DATE'] if x['HOUR'] <= 12 else datetime.timedelta(days=1) + x['DATE'], axis=1)
#         df['PREC'] = df.groupby(['FOR_DATE'])['PRECIP'].transform('sum')
#         daily = df[df['HOUR'] == 12][['DATE', 'PREC', 'TEMP', 'RH', 'WS', 'WD']]
#         daily.columns = ['Date', 'APCP', 'TMP', 'RH', 'WS', 'WD']
#         daily['Scenario'] = -1
#         daily = daily[['Scenario', 'Date', 'APCP', 'TMP', 'RH', 'WS', 'WD']]
#         daily['Date'] = daily['Date'].apply(lambda x: str(x + datetime.timedelta(hours=13)))
#         daily.to_csv('wx.csv', index=False)
#         cmd = "./tbd"
#         args = "{} {} {} {} {}:{:02d} -v --output_date_offsets \"{{1, 2, 3}}\" --wx wx.csv --ffmc {} --dmc {} --dc {} --apcp_0800 {}".format(out_dir, start_date, lat, long, hour, minute, ffmc, dmc, dc, apcp_0800)
#         if perim is not None:
#             args = args + " --perim {}".format(perim)
#         # run generated command for parsing data
#         run_what = [cmd] + shlex.split(args.replace('\\', '/'))
#         logging.info("Running: " + ' '.join(run_what))
#         t0 = timeit.default_timer()
#         stdout, stderr = common.finish_process(common.start_process(run_what, "/appl/tbd"))
#         t1 = timeit.default_timer()
#         logging.info("Took {}s to run simulations".format(t1 - t0))
#         log_name = os.path.join(out_dir, "log.txt")
#         with open(log_name, 'w') as log_file:
#             log_file.write(stdout.decode('utf-8'))
#         outputs = sorted(os.listdir(out_dir))
#         extent = None
#         probs = [x for x in outputs if x.endswith('tif') and x.startswith('probability')]
#         if len(probs) > 0:
#             prob = probs[-1]
#             extent = gis.project_raster(os.path.join(out_dir, prob), os.path.join(PROB_DIR, job_date, region, fire_name + '.tif'))
#         perims = [x for x in outputs if x.endswith('tif') and not (x.startswith('probability') or x.startswith('intensity'))]
#         if len(perims) > 0:
#             perim = perims[0]
#             gis.project_raster(os.path.join(out_dir, perim),
#                                          os.path.join(PERIM_DIR, job_date, region, fire_name + '.tif'),
#                                          outputBounds=extent)
#     else:
#         return None
#     return log_name

# dir_in = '/home/bfdata/202306061927/TIM_FIRE_007'

def run_fire_from_folder(dir_in):
    with open(os.path.join(dir_in, 'firestarr.json')) as f:
      data = json.load(f)
    region = os.path.basename(os.path.dirname(os.path.dirname(dir_in)))
    lat = data['lat']
    long = data['long']
    # job_name = os.path.basename(dir_in)
    # job_time = job_name[job_name.rindex('_') + 1:]
    # job_date = job_time[:8]
    job_time = data['job_time']
    job_date = data['job_date']
    fire_name = data['fire_name']
    start_time = data['start_time']
    start_time = pd.to_datetime(start_time)
    logging.info("Scenario start time is: {}".format(start_time))
    # out_dir = os.path.join(ROOT_DIR, job_date, region, fire_name, job_time)
    dir_out = data['dir_out']
    # done_already = os.path.exists(out_dir)
    done_already = False
    if not done_already:
        common.ensure_dir(dir_out)
        # project = data['project']
        # pt = None
        # ignition = try_read_first(project['ignitions'], 'ignitions', is_fatal=True)
        # ign = try_read_first(ignition['ignition']['ignitions'], 'ignitions', is_fatal=True)
        # perim = None
        # poly = ign['polygon']
        # if poly['units'] != 'LAT_LON':
        #     logging.fatal("Only lat/long coordinates are currently supported")
        #     sys.exit(-1)
        if True:
        # if ign['polyType'] != 'POINT':
            if data['perim'] is not None:
            # if ign['polyType'] == 'POLYGON_OUT':
                perim = os.path.join(dir_in, data['perim'])
                logging.debug(f'Perimeter input is {perim}')
                # # pts = poly['polygon']['points']
                # # pts = list(map(unnest_values, pts))
                # # pts = [list(map(lambda v: [v['x'], v['y']], pts))]
                # # lat = statistics.mean(list(map(lambda v: v[1], pts[0])))
                # # long = statistics.mean(list(map(lambda v: v[0], pts[0])))
                # # print(long)
                # orig_zone = 15
                # orig_long = -93
                # diff = long - orig_long
                # # print(diff)
                # ZONE_SIZE = 6
                # zone_diff = round(diff / ZONE_SIZE)
                # # print(zone_diff)
                # meridian = orig_long + (zone_diff * ZONE_SIZE)
                # # print(meridian)
                # zone = orig_zone + zone_diff
                # # # print(pts)
                # # p = '''{"type": "Polygon",
                # #         "coordinates": ''' + str(pts) + ''',
                # #     }'''
                # # # print(p)
                # # g = ogr.CreateGeometryFromJson(p)
                # # # print(g)
                # # # print("Hi! I'm a %s with an Area  %s" % (g.GetGeometryName(), g.Area()))
                # # # print("I have inside me %s feature(s)!\n" % g.GetGeometryCount())
                # # # for idx, f in enumerate(g):
                # #     # print("I'm feature n.%s and I am a %s.\t I have an Area of %s - You can get my json repr with f.ExportToJson()" % (idx, f.GetGeometryName(),f.Area()))
                # source = osr.SpatialReference()
                # source.ImportFromEPSG(4269)
                # target = osr.SpatialReference()
                # target.ImportFromEPSG(3159)
                # z = target.ExportToWkt()
                # z = z[:z.rindex(",AUTHORITY")] + "]"
                # z = z.replace('UTM zone 15N', 'UTM zone {}N')
                # z = z.replace('"central_meridian",-93', '"central_meridian",{}')
                # z = z.format(zone, meridian)
                # # print(z)
                # # print(target)
                # target.ImportFromWkt(z)
                # # transform = osr.CoordinateTransformation(source, target)
                # # g.Transform(transform)
                # # #print(g)
                # # # logging.debug("Hi! I'm a %s with an Area  %s" % (g.GetGeometryName(), g.Area()))
                # # # logging.debug("I have inside me %s feature(s)!\n" % g.GetGeometryCount())
                # # # for idx, f in enumerate(g):
                # #     # logging.debug("I'm feature n.%s and I am a %s.\t I have an Area of %s - You can get my json repr with f.ExportToJson()" % (idx, f.GetGeometryName(),f.Area()))
                out_name = '{}.shp'.format(fire_name)
                out_file = os.path.join(dir_out, out_name)
                p = gpd.read_file(perim)
                p.to_file(out_file)
                # gis.Project(perim, out_file, target)
                # # driver = ogr.GetDriverByName("Esri Shapefile")
                # # ds = driver.CreateDataSource(out_file)
                # # layr1 = ds.CreateLayer('', None, ogr.wkbPolygon)
                # # # create the field
                # # layr1.CreateField(ogr.FieldDefn('id', ogr.OFTInteger))
                # # # Create the feature and set values
                # # defn = layr1.GetLayerDefn()
                # # feat = ogr.Feature(defn)
                # # feat.SetField('id', 1)
                # # feat.SetGeometry(g)
                # # layr1.CreateFeature(feat)
                # # # close the shapefile
                # # ds.Destroy()
                # target.MorphToESRI()
                # with open(os.path.join(out_dir, '{}.prj'.format(fire_name)), 'w') as file:
                #     file.write(target.ExportToWkt())
                # run_output = dir_out
                # perim = out_file
                # year = start_time.year
                # name = fire_name
                perim = gis.rasterize_perim(dir_out, out_file, start_time.year, fire_name)[1]
            else:
                logging.fatal("Unsupported ignition type {}".format(ign['polyType']))
            if perim is None:
                sys.exit(-1)
        # else:
        #     pt = try_read_first(poly['polygon'], 'points', is_fatal=True)
        #     if pt is None:
        #         # should have already exited but check
        #         logging.fatal("Ignition point not initialized")
        #         sys.exit(-1)
        #     unnest_values(pt)
        #     lat = pt['y']
        #     long = pt['x']
        logging.info("Startup coordinates are {}, {}".format(lat, long))
        hour = start_time.hour
        minute = start_time.minute
        tz = start_time.tz.utcoffset(start_time).total_seconds() / 60.0 / 60.0
        # HACK: I think there might be issues with forecasts being at the half hour?
        if math.floor(tz) != tz:
            logging.fatal("Currently not set up to deal with partial hour timezones")
            sys.exit(-1)
        tz = int(tz)
        logging.info("Timezone offset is {}".format(tz))
        # date_offset = 0
        start_date = start_time.date()
        # if start_date != datetime.date.today():
        #     date_offset = (start_date - datetime.date.today()).days
        #     logging.warning("Simulation does not start today - date offset set to {}".format(date_offset))
        cmd = "./tbd"
        wx_file = os.path.join(dir_out, 'wx.csv')
        shutil.copy(os.path.join(dir_in, data['wx']), wx_file)
        # date_offsets = [1, 2]
        date_offsets = data['offsets']
        args = "\"{}\" {} {} {} {:02d}:{:02d} -v --output_date_offsets \"{}\" --wx \"{}\"".format(
            dir_out, start_date, lat, long, hour, minute, "{" + ", ".join([str(x) for x in date_offsets]) + "}", wx_file)
        if perim is not None:
            args = args + " --perim \"{}\"".format(perim)
        args = args.replace('\\', '/')
        logging.info(f'Running: {cmd} {args}')
        # run generated command for parsing data
        run_what = [cmd] + shlex.split(args)
        t0 = timeit.default_timer()
        stdout, stderr = common.finish_process(common.start_process(run_what, "/appl/tbd"))
        t1 = timeit.default_timer()
        logging.info("Took {}s to run simulations".format(t1 - t0))
        log_name = os.path.join(dir_out, "log.txt")
        with open(log_name, 'w') as log_file:
            log_file.write(stdout.decode('utf-8'))
        outputs = sorted(os.listdir(dir_out))
        extent = None
        probs = [x for x in outputs if x.endswith('tif') and x.startswith('probability')]
        if len(probs) > 0:
            prob = probs[-1]
            extent = gis.project_raster(os.path.join(dir_out, prob), os.path.join(PROB_DIR, job_date, region, fire_name + '.tif'))
        perims = [x for x in outputs if x.endswith('tif') and not (x.startswith('probability') or x.startswith('intensity'))]
        if len(perims) > 0:
            perim = perims[0]
            gis.project_raster(os.path.join(dir_out, perim),
                                         os.path.join(PERIM_DIR, job_date, region, fire_name + '.tif'),
                                         outputBounds=extent)
    else:
        return None
    return log_name


if __name__ == "__main__":
    run_fire_from_folder(sys.argv[1])

# python tbd.py /home/bfdata/session_20230604_084639_688567/outputs/canada/fires/54967
# ./tbd "/appl/data/sims/20230605/canada/54967 unassigned 2023-Jun-04/1542" 2023-06-05 48.92 -76.43 10:47 -v --output_date_offsets "{1, 2}" --wx "/appl/data/sims/20230605/canada/54967 unassigned 2023-Jun-04/1542/wx.csv" --perim "/appl/data/sims/20230605/canada/54967 unassigned 2023-Jun-04/1542/54967 unassigned 2023-Jun-04.tif" -v -v -v

# make && ./tbd "/appl/data/sims/20230605/canada/54967 unassigned 2023-Jun-04/1542" 2023-06-05 48.92 -76.43 10:47 -v --output_date_offsets "{1, 2}" --wx "/appl/data/sims/20230605/canada/54967 unassigned 2023-Jun-04/1542/wx.csv" --perim "/appl/data/sims/20230605/canada/54967 unassigned 2023-Jun-04/1542/54967 unassigned 2023-Jun-04.tif" -v -v
