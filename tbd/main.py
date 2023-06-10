# import libraries
import urllib.request as urllib2
from bs4 import BeautifulSoup
import pandas as pd
import os
import datetime
import sys

sys.path.append("../util")
import common
from common import ensure_dir
import model_data
import tbd
import timeit
import logging
import shutil
import shlex
import sys
import numpy as np
import geopandas as gpd

sys.path.append(os.path.dirname(sys.executable))
sys.path.append("/usr/local/bin")
import osgeo
import osgeo.utils
import osgeo.utils.gdal_merge as gm
import osgeo.utils.gdal_retile as gr
import osgeo.utils.gdal_calc as gdal_calc
import itertools
import json
import pytz
import pyproj
import timezonefinder
import subprocess


sys.path.append('./cffdrs-ng')
import NG_FWI

import tbd


DIR = "/appl/data/fgmj/"
EXT_DIR = os.path.abspath(os.path.join(DIR, "../extracted/fgmj"))
ensure_dir(EXT_DIR)
CREATION_OPTIONS = ["COMPRESS=LZW", "TILED=YES"]
# CRS_NAD83 = 4269
# CRS_NAD83_CSRS = 4617
# want a projection that's NAD83 based, project, and units are degrees
# CRS = "ESRI:102002"
CRS = 4269

def getPage(url):
    logging.debug("Opening {}".format(url))
    # query the website and return the html to the variable 'page'
    page = urllib2.urlopen(url)
    # parse the html using beautiful soup and return
    return BeautifulSoup(page, "html.parser")


# def run_fires(dir_cur, region):
#     dir_region = os.path.join(dir_cur, region, "fires")
#     jobs = os.listdir(dir_region)
#     times = {}
#     recent = {}
#     simtimes = {}
#     dates = []
#     totaltime = 0
#     logging.debug("Checking {} jobs".format(len(jobs)))
#     by_fire = {}
#     today = str(datetime.datetime.today()).replace("-", "")[:8]
#     # dates = [today]
#     for j in jobs:
#         scenario = os.path.join(dir_region, j, "firestarr.json")
#         if os.path.exists(scenario):
#             with open(scenario) as f:
#                 data = json.load(f)
#             fire_name = data["fire_name"]
#             if not fire_name in by_fire:
#                 by_fire[fire_name] = []
#             by_fire[fire_name] = by_fire[fire_name] + [scenario]
#     for fire_name in by_fire.keys():
#         scenario = sorted(by_fire[fire_name])[-1]
#         cur_dir = os.path.dirname(scenario)
#         try:
#             t0 = timeit.default_timer()
#             log_name = tbd.run_fire_from_folder(cur_dir)
#             t1 = timeit.default_timer()
#             if log_name is not None:
#                 simtimes[j] = t1 - t0
#                 totaltime = totaltime + simtimes[j]
#                 logging.info("Took {}s to run {}".format(simtimes[j], j))
#                 d = os.path.basename(os.path.dirname(log_name))[:8]
#                 if d not in dates:
#                     dates.append(d)
#         except Exception as e:
#             logging.error(e)
#     return simtimes, totaltime, dates


# def run_fires(site, region):
#     site = 'https://cfsdip.intellifirenwt.com'
#     region = 'canada'
#     url = site + '/jobs/'
#     try:
#         p = getPage(url)
#     except Exception as e:
#         logging.error("Can't load {}".format(url))
#         logging.error(e)
#         return None
#     a = p.findAll('a')
#     dirs = [x.get('href') for x in a if x.get('href').startswith('/jobs/job_')]
#     jobs = sorted(set([x[x.rindex('/') + 1:] for x in dirs]))
#     times = {}
#     recent = {}
#     simtimes = {}
#     dates = []
#     totaltime = 0
#     dir_download = ensure_dir(os.path.join(DIR, region))
#     dir_ext = ensure_dir(os.path.join(EXT_DIR, region))
#     logging.debug("Checking {} jobs".format(len(jobs)))
#     by_fire = {}
#     today = str(datetime.datetime.today()).replace('-', '')[:8]
#     dates = [today]
#     for j in jobs:
#         if j.startswith("job_" + today):
#             # job_p = getPage(url + j + "/Inputs")
#             cur_dir = os.path.join(dir_download, j)
#             fgmj = common.save_http(cur_dir, url + j + "/job.fgmj", ignore_existing=True)
#             if os.path.exists(fgmj):
#                 with open(fgmj) as f:
#                     data = json.load(f)
#                 scenario_name = data['project']['scenarios']['scenarios'][0]['name']
#                 fire_name = scenario_name[:scenario_name.index(' ')]
#                 if not fire_name in by_fire:
#                     by_fire[fire_name] = []
#                 by_fire[fire_name] = by_fire[fire_name] + [fgmj]
#     for fire_name in by_fire.keys():
#         fgmj = sorted(by_fire[fire_name])[-1]
#         cur_dir = os.path.dirname(fgmj)
#         with open(fgmj) as f:
#             data = json.load(f)
#         wx_file = data['project']['stations']['stations'][0]['station']['streams'][0]['condition']['filename']
#         wx = common.save_http(os.path.join(cur_dir, os.path.dirname(wx_file)), url + j + "/" + wx_file, ignore_existing=True)
#         try:
#             t0 = timeit.default_timer()
#             log_name = tbd.do_run(fgmj)
#             t1 = timeit.default_timer()
#             if log_name is not None:
#                 simtimes[j] = t1 - t0
#                 totaltime = totaltime + simtimes[j]
#                 logging.info("Took {}s to run {}".format(simtimes[j], j))
#                 d = os.path.basename(os.path.dirname(log_name))[:8]
#                 if d not in dates:
#                     dates.append(d)
#         except Exception as e:
#             logging.error(e)
#     return simtimes, totaltime, dates


def merge_dir(dir_in, force=False):
    logging.info("Merging {}".format(dir_in))
    # HACK: for some reason output tiles were both being called 'probability'
    import importlib
    from osgeo import gdal
    use_exceptions = gdal.GetUseExceptions()
    # HACK: if exceptions are on then gdal_merge throws one
    gdal.DontUseExceptions()
    importlib.reload(gr)
    TILE_SIZE = str(1024)
    co = list(
        itertools.chain.from_iterable(map(lambda x: ["-co", x], CREATION_OPTIONS))
    )
    dir_base = os.path.dirname(dir_in)
    dir_parent = os.path.dirname(dir_base)
    dir_type = os.path.basename(dir_base)
    # want to put probability and perims together
    dir_out = common.ensure_dir(os.path.join(dir_parent,
                                             'combined',
                                             #  os.path.basename(dir_base),
                                             os.path.basename(dir_in)))
    files_by_for_what = {}
    for region in os.listdir(dir_in):
        dir_region = os.path.join(dir_in, region)
        if os.path.isdir(dir_region):
            for for_what in os.listdir(dir_region):
                dir_for_what = os.path.join(dir_region, for_what)
                files_by_for_what[for_what] = files_by_for_what.get(for_what, []) + [
                    os.path.join(dir_for_what, x)
                    for x in sorted(os.listdir(dir_for_what))
                    if x.endswith(".tif")
                ]
    ymd_origin = os.path.basename(dir_in)
    date_origin = datetime.datetime.strptime(ymd_origin, '%Y%m%d')
    for for_what, files in files_by_for_what.items():
        dir_in_for_what = os.path.basename(for_what)
        if 'perim' == dir_in_for_what:
            dir_for_what = 'perim'
            title = f"FireSTARR - {ymd_origin} Input Perimeters"
        else:
            date_cur = datetime.datetime.strptime(dir_in_for_what, '%Y%m%d')
            offset = (date_cur - date_origin).days + 1
            dir_for_what = f'firestarr_day_{offset:02d}'
            title = f"FireSTARR - {ymd_origin} Day {offset:02d}"
        file_root = os.path.join(dir_out, dir_for_what)
        file_tmp = f"{file_root}_tmp.tif"
        file_out = f"{file_root}.tif"
        file_int = f"{file_root}_int.tif"
        dir_tile = file_root
        if os.path.exists(dir_tile):
            if force:
                logging.info("Removing {}".format(dir_tile))
                shutil.rmtree(dir_tile)
            else:
                logging.info(f"Output {dir_tile} already exists")
                return dir_tile
        gm.main(["", "-n", "0", "-a_nodata", "0"] + co + ["-o", file_tmp] + files)
        # gm.main(['', '-n', '0', '-a_nodata', '0', '-co', 'COMPRESS=DEFLATE', '-co', 'ZLEVEL=9', '-co', 'TILED=YES', '-o', file_tmp] + files)
        shutil.move(file_tmp, file_out)
        if 'perim' != dir_in_for_what:
            # only calculate int output if looking at probability
            logging.debug("Calculating...")
            gdal_calc.Calc(
                A=file_out,
                outfile=file_tmp,
                calc="A*100",
                NoDataValue=0,
                type="Byte",
                creation_options=CREATION_OPTIONS,
                quiet=True,
            )
            shutil.move(file_tmp, file_int)
            # apply symbology to probability
            file_cr = f"{file_root}_cr.tif"
            logging.debug("Applying symbology...")
            subprocess.run(
                "gdaldem color-relief {} /appl/tbd/col.txt {} -alpha -co COMPRESS=LZW -co TILED=YES".format(
                    file_int, file_cr
                ),
                shell=True,
            )
            file_out = file_cr
        dir_tile = ensure_dir(dir_tile)
        args = f"-a 0 -z 5-12 {file_out} {dir_tile} -t \"{title}\" --processes={os.cpu_count()}"
        logging.debug(
            f"python gdal2tiles.py {args}"
        )
        subprocess.run(
            f"python /appl/.venv/bin/gdal2tiles.py {args}",
            shell=True,
        )
        logging.info(f"Made tiles for {for_what}...")
    if use_exceptions:
        gdal.UseExceptions()
    return dir_tile


PLACEHOLDER_TITLE = "__TITLE__"


def merge_dirs(dir_input, dates=None):
    results = []
    for d in sorted(os.listdir(dir_input)):
        if dates is None or d in dates:
            dir_in = os.path.join(dir_input, d)
            results.append(merge_dir(dir_in))
    if 0 == len(results):
        logging.warning(f"No directories merged from {dir_input}")
        return
    # result = '/appl/data/output/combined/probability/20230610'
    # result should now be the results for the most current day
    # dir_out = os.path.join(os.path.dirname(dir_input), "current", os.path.basename(dir_input))
    result = results[-1]
    FILE_HTML = '/appl/data/output/firestarr.html'
    title = f'FireSTARR - {os.path.basename(result.rstrip("/"))}'
    with open(FILE_HTML, 'r') as f_in:
        with open(f'{result}/{os.path.basename(FILE_HTML)}', 'w') as f_out:
            f_out.writelines([line.replace(PLACEHOLDER_TITLE, title) for line in f_in.readlines()])
    return result
    # dir_out = os.path.join(os.path.dirname(dir_input), "current")
    # logging.info(f"Moving results to {dir_out}")
    # if os.path.exists(dir_out):
    #     logging.info("Removing existing results")
    #     shutil.rmtree(dir_out)
    # logging.info(f"Copying {result} to {dir_out}")
    # shutil.copytree(result, dir_out)



def get_fires_m3(dir_out):
    df_fires, fires_json = model_data.get_fires_m3(dir_out)
    df_fires['guess_id'] = df_fires['guess_id'].replace(np.nan, None)
    df_fires['fire_name'] = df_fires.apply(lambda x: (x['guess_id'] or x['id']).replace(' ', '_'), axis=1)
    return df_fires


def get_fires_folder(dir_fires, crs='EPSG:3347'):
    proj = pyproj.CRS(crs)
    df_fires = None
    for root, dirs, files in os.walk(dir_fires):
        for f in [x for x in files if x.lower().endswith(".shp")]:
            file_shp = os.path.join(root, f)
            df_fire = gpd.read_file(file_shp).to_crs(proj)
            df_fires = pd.concat([df_fires, df_fire])
    df_fires['fire_name'] = df_fires['FIRENUMB']
    return df_fires


# dir_fires = "/home/bfdata/affes/latest"
def run_all_fires(dir_fires=None):
    DIR_ROOT = "/home/bfdata"
    run_start = datetime.datetime.now()
    run_id = run_start.strftime("%Y%m%d%H%M")
    dir_out = ensure_dir(os.path.join(DIR_ROOT, run_id))
    today = run_start.date()
    yesterday = today - datetime.timedelta(days=1)
    # NOTE: use NAD 83 / Statistics Canada Lambert since it should do well with distances
    crs = 'EPSG:3347'
    proj = pyproj.CRS(crs)
    if dir_fires is None:
        df_fires = get_fires_m3(dir_out)
    else:
        df_fires = get_fires_folder(dir_fires, crs)
    df_fires = df_fires.to_crs(crs)
    # HACK: can't just convert to lat/long crs and use centroids from that because it causes a warning
    centroids = df_fires.centroid.to_crs(CRS)
    df_fires['lon'] = centroids.x
    df_fires['lat'] = centroids.y
    df_fires['area_calc'] = df_fires.area
    # df_fires = df_fires.to_crs(CRS)
    df_fires = df_fires.sort_values(['area_calc'])
    df_wx_cwfis = model_data.get_wx_cwfis(dir_out, [today, yesterday])
    df_wx_cwfis_wgs = df_wx_cwfis.to_crs(proj)
    # results = {r: run_fires(dir_cur, r) for r in os.listdir(os.path.join(dir_cur))}
    results = {}
    times = {}
    recent = {}
    simtimes = {}
    dates = []
    totaltime = 0
    tf = timezonefinder.TimezoneFinder()
    for fireid, next_fire in df_fires.iterrows():
        print(next_fire)
        fire_name = next_fire['fire_name']
        dir_fire = ensure_dir(os.path.join(dir_out, fire_name))
        logging.debug(f'Saving {fire_name} to {dir_fire}')
        lat = next_fire['lat']
        lon = next_fire['lon']
        # we can use this directly because it's a projected coordinate
        pt_centroid = df_fires.centroid.iloc[fireid]
        tzone = tf.timezone_at(lng=lon, lat=lat)
        timezone = pytz.timezone(tzone)
        # HACK: America/Inuvik is giving an offset of 0 when applied directly, but says -6 otherwise
        utcoffset = timezone.utcoffset(run_start)
        utcoffset_hours = utcoffset.total_seconds() / 60 / 60
        df_fire = gpd.GeoDataFrame([next_fire], crs=df_fires.crs)
        file_fire = os.path.join(dir_fire, '{}_NAD1983.geojson'.format(fire_name))
        df_fire.to_file(file_fire)
        df_wx = df_wx_cwfis_wgs.iloc[:]
        df_wx['dist'] = df_wx.distance(pt_centroid)
        # figure out startup indices yesterday
        df_wx_actual = df_wx[df_wx['dist'] == min(df_wx['dist'])]
        # df_wx_spotwx = model_data.get_wx_spotwx(lat, lon)
        df_wx_spotwx = model_data.get_wx_ensembles(lat, lon)
        df_wx_filled = model_data.wx_interpolate(df_wx_spotwx)
        df_wx_fire = df_wx_filled.rename(columns={
            'datetime': 'TIMESTAMP',
            'precip': 'PREC'
        })
        df_wx_fire.columns = [s.upper() for s in df_wx_fire.columns]
        df_wx_fire['YR'] = df_wx_fire.apply(lambda x: x['TIMESTAMP'].year, axis=1)
        df_wx_fire['MON'] = df_wx_fire.apply(lambda x: x['TIMESTAMP'].month, axis=1)
        df_wx_fire['DAY'] = df_wx_fire.apply(lambda x: x['TIMESTAMP'].day, axis=1)
        df_wx_fire['HR'] = df_wx_fire.apply(lambda x: x['TIMESTAMP'].hour, axis=1)
        # cols = df_wx_fire.columns
        ffmc_old, dmc_old, dc_old = df_wx_actual.iloc[0][['ffmc', 'dmc', 'dc']]
        # HACK: just get something for now
        have_noon = [x.date() for x in df_wx_fire[df_wx_fire['HR'] == 12]['TIMESTAMP']]
        df_wx_fire = df_wx_fire[[x.date() in have_noon for x in df_wx_fire['TIMESTAMP']]]
        # noon = datetime.datetime.fromordinal(today.toordinal()) + datetime.timedelta(hours=12)
        # df_wx_fire = df_wx_fire[df_wx_fire['TIMESTAMP'] >= noon].reset_index()[cols]
        df_fwi = NG_FWI.hFWI(df_wx_fire, utcoffset_hours, ffmc_old, dmc_old, dc_old)
        # COLUMN_SYNONYMS = {'WIND': 'WS', 'RAIN': 'PREC', 'YEAR': 'YR', 'HOUR': 'HR'}
        df_wx = df_fwi.rename(columns={
            "TIMESTAMP": "Date",
            "ID": "Scenario",
            "RAIN": "APCP",
            "TEMP": "TMP",
            "WIND": "WS"})
        df_wx = df_wx[
            [
                "Scenario",
                "Date",
                "APCP",
                "TMP",
                "RH",
                "WS",
                "WD",
                "FFMC",
                "DMC",
                "DC",
                "ISI",
                "BUI",
                "FWI",
            ]
        ]
        df_wx.round(2).to_csv(os.path.join(dir_fire, "wx.csv"), index=False, quoting=False)
        # start_time = run_start.astimezone(timezone)
        start_time = min(df_wx['Date']).tz_localize(timezone)
        # HACK: don't start right at midnight because the hour before is missing
        if (6 > start_time.hour):
            start_time = start_time.replace(hour=6, minute=0, second=0)
        WANT_DATES = [1, 2, 3, 7, 14]
        # WANT_DATES = [1, 2, 3]
        max_days = (df_wx['Date'].max() - df_wx['Date'].min()).days
        offsets = [x for x in WANT_DATES if x < max_days]
        data = {
            "wx": "wx.csv",
            "job_date": run_start.strftime("%Y%m%d"),
            "job_time": run_start.strftime("%H%M"),
            "start_time": start_time.isoformat(),
            "lat": lat,
            "lon": lon,
            "perim": os.path.basename(file_fire),
            # "agency": fire.config.agency,
            # "fireid": fire.fireid,
            "dir_out": os.path.join(dir_fire, 'firestarr'),
            "fire_name": fire_name,
            "offsets": offsets,
        }
        with open(os.path.join(dir_fire, "firestarr.json"), "w") as f:
            json.dump(data, f)
        # cmd = f"sshpass -p password ssh -l user -p 22 tbd 'cd /appl/tbd && python tbd.py \"{fire.curdir}\"'"
        # # run generated command for parsing data
        # # run_what = [cmd] + shlex.split(args.replace('\\', '/'))
        # run_what = shlex.split(cmd)
        # print("Running: " + " ".join(run_what))
        try:
            t0 = timeit.default_timer()
            log_out = tbd.run_fire_from_folder(dir_fire)
            t1 = timeit.default_timer()
            t = t1 - t0
            print("Took {}s to run simulations".format(t))
            results[fire_name] = {
                'duration': t,
            }
            totaltime = totaltime + t
        except RuntimeError as e:
            logging.warning(e)
            results[fire_name] = None
            # raise e
    # dir_cur = os.path.join(DIR_ROOT, os.listdir(DIR_ROOT)[-1], "outputs")
    # results = {r: run_fires(dir_cur, r) for r in os.listdir(os.path.join(dir_cur))}
    # simtimes = {}
    # dates = []
    # totaltime = 0
    # for k in results.keys():
    #     if results[k] is not None:
    #         s, t, d = results[k]
    #         for f in s.keys():
    #             simtimes["{}_{}".format(k, f)] = s[f]
    #         dates = sorted(dates + [x for x in d if x not in dates])
    #         totaltime = totaltime + t
    # return simtimes, totaltime, dates
    return dir_out, results

def merge_outputs(dir_out):
    for fire_name in [x for x in os.listdir(dir_out) if os.path.isdir(os.path.join(dir_out, x))]:
        dir_fire = os.path.join(dir_out, fire_name)
        print(dir_fire)
        log_out = tbd.run_fire_from_folder(dir_fire)
    merge_dirs("/appl/data/output/initial")


# this was okay when using the other container
# def run_all_fires():
#     DIR_ROOT = '/home/bfdata'
#     dir_cur = os.path.join(DIR_ROOT, os.listdir(DIR_ROOT)[-1], 'outputs')
#     results = {r: run_fires(dir_cur, r) for r in os.listdir(os.path.join(dir_cur))}
#     simtimes = {}
#     dates = []
#     totaltime = 0
#     for k in results.keys():
#         if results[k] is not None:
#             s, t, d = results[k]
#             for f in s.keys():
#                 simtimes['{}_{}'.format(k, f)] = s[f]
#             dates = sorted(dates + [x for x in d if x not in dates])
#             totaltime = totaltime + t
#     return simtimes, totaltime, dates


# def run_all_fires():
#     results = {}
#     results['canada'] = run_fires('https://cfsdip.intellifirenwt.com', 'canada')
#     simtimes = {}
#     dates = []
#     totaltime = 0
#     for k in results.keys():
#         if results[k] is not None:
#             s, t, d = results[k]
#             for f in s.keys():
#                 simtimes['{}_{}'.format(k, f)] = s[f]
#             dates = sorted(dates + [x for x in d if x not in dates])
#             totaltime = totaltime + t
#     return simtimes, totaltime, dates

if __name__ == "__main__":
    dir_job, results = run_all_fires(sys.argv[1] if len(sys.argv) > 1 else None)
    # simtimes, totaltime, dates = run_all_fires()
    n = len(results)
    if n > 0:
        # logging.info(
        #     "Total of {} fires took {}s - average time is {}s".format(
        #         n, totaltime, totaltime / n
        #     )
        # )
        # merge_dirs("/appl/data/output/probability", dates)
        # merge_dirs("/appl/data/output/perimeter", dates)
        merge_dirs("/appl/data/output/initial")
