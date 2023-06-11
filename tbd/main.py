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
from tqdm import tqdm
import tqdm_pool

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
import subprocess

sys.path.append('./cffdrs-ng')
import NG_FWI

import tbd
from tbd import FILE_SIM

DIR = "/appl/data/fgmj/"
EXT_DIR = os.path.abspath(os.path.join(DIR, "../extracted/fgmj"))
ensure_dir(EXT_DIR)
CREATION_OPTIONS = ["COMPRESS=LZW", "TILED=YES"]
# CRS_NAD83 = 4269
# CRS_NAD83_CSRS = 4617
# want a projection that's NAD83 based, project, and units are degrees
# CRS = "ESRI:102002"
CRS = 4269
PLACEHOLDER_TITLE = "__TITLE__"
FILE_HTML = '/appl/data/output/firestarr.html'
WANT_DATES = [1, 2, 3, 7, 14]


def getPage(url):
    logging.debug("Opening {}".format(url))
    # query the website and return the html to the variable 'page'
    page = urllib2.urlopen(url)
    # parse the html using beautiful soup and return
    return BeautifulSoup(page, "html.parser")


def merge_dir(dir_in, run_id, force=False):
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
        file_base = f"{file_root}.tif"
        file_int = f"{file_root}_int.tif"
        dir_tile = os.path.join(dir_out, dir_for_what)
        if os.path.exists(dir_tile):
            if force:
                logging.info("Removing {}".format(dir_tile))
                shutil.rmtree(dir_tile)
            else:
                logging.info(f"Output {dir_tile} already exists")
                return dir_tile
        gm.main(["", "-n", "0", "-a_nodata", "0"] + co + ["-o", file_tmp] + files)
        # gm.main(['', '-n', '0', '-a_nodata', '0', '-co', 'COMPRESS=DEFLATE', '-co', 'ZLEVEL=9', '-co', 'TILED=YES', '-o', file_tmp] + files)
        shutil.move(file_tmp, file_base)
        file_out = file_base
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
    dir_rasters = ensure_dir(os.path.join(dir_out, 'rasters'))
    logging.info(f"Moving rasters to {dir_rasters}")
    for file in [x for x in os.listdir(dir_out) if not x.endswith('.html')]:
        file_in = os.path.join(dir_out, file)
        if os.path.isfile(file_in):
            shutil.move(file_in, os.path.join(dir_rasters, file))
    title = f'FireSTARR - {run_id}'
    with open(FILE_HTML, 'r') as f_in:
        file_html = os.path.join(dir_out, os.path.basename(FILE_HTML))
        with open(file_html, 'w') as f_out:
            f_out.writelines([line.replace(PLACEHOLDER_TITLE, title) for line in f_in.readlines()])
    if use_exceptions:
        gdal.UseExceptions()
    return dir_out


def merge_dirs(dir_input, dates=None):
    # expecting dir_input to be a path ending in a runid of form '%Y%m%d%H%M'
    dir_initial = os.path.join(dir_input, "initial")
    run_id = os.path.basename(dir_input)
    results = []
    # this expects folders to be '%Y%m%d' for start day for runs
    # NOTE: should really only have one folder in here if we're saving to dir_input for each run
    for d in sorted(os.listdir(dir_initial)):
        if dates is None or d in dates:
            dir_in = os.path.join(dir_initial, d)
            results.append(merge_dir(dir_in, run_id))
    if 0 == len(results):
        logging.warning("No directories merged from %s", dir_initial)
        return
    # result = '/appl/data/output/combined/probability/20230610'
    # result should now be the results for the most current day
    # dir_out = os.path.join(os.path.dirname(dir_input), "current", os.path.basename(dir_input))
    result = results[-1]
    logging.info("Final results of merge are in %s", result)
    dir_zip = os.path.dirname(dir_input)
    run_id = os.path.basename(dir_input)
    file_zip = os.path.join(dir_zip, f"{os.path.basename(dir_zip)}_{run_id}.zip")
    logging.info("Creating archive %s", file_zip)
    z = common.zip_folder(file_zip, result)
    # # add a '/' so it uses the contents but not the folder
    # args = [
    #     "-c",
    #     file_zip,
    #     f"{result}/"
    # ]
    # # z = zipfile.main(*args)
    # # args = f'-c "{file_zip}" "{result}    "'
    # z = zipfile.main(args)
    # want to zip up this folder
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


# def prepare_run_fire(dir_out, run_start, tf, df_fire, df_wx, max_days=None):
# def run_fire(dir_out, run_start, tf, df_fire, df_wx, dir_current, max_days=None):
def make_run_fire(dir_out, df_fire, run_start, ffmc_old, dmc_old, dc_old, max_days=None):
    if 1 != len(df_fire):
        raise RuntimeError("Expected exactly one row for run_fire()")
    next_fire = df_fire.iloc[0]
    # print(next_fire)
    # we can use this directly because it's a projected coordinate
    # pt_centroid = df_fire.centroid.iloc[0]
    fire_name = next_fire['fire_name']
    dir_fire = ensure_dir(os.path.join(dir_out, fire_name))
    logging.debug('Saving %s to %s', fire_name, dir_fire)
    lat = next_fire['lat']
    lon = next_fire['lon']
    file_fire = os.path.join(dir_fire, '{}_NAD1983.geojson'.format(fire_name))
    df_fire.to_file(file_fire)
    data = {
        "job_date": run_start.strftime("%Y%m%d"),
        "job_time": run_start.strftime("%H%M"),
        'ffmc_old': ffmc_old,
        'dmc_old': dmc_old,
        'dc_old': dc_old,
        "lat": lat,
        "lon": lon,
        "perim": os.path.basename(file_fire),
        "dir_out": os.path.join(dir_fire, 'firestarr'),
        "fire_name": fire_name,
        "max_days": max_days,
    }
    with open(os.path.join(dir_fire, FILE_SIM), "w") as f:
        json.dump(data, f)
    return dir_fire


def do_run_fire(for_what):
    dir_fire, dir_current = for_what
    # load and update the configuration with more data
    with open(os.path.join(dir_fire, FILE_SIM)) as f:
        data = json.load(f)
    lat = data['lat']
    lon = data['lon']
    # need for offset and wx
    import timezonefinder
    tf = timezonefinder.TimezoneFinder()
    tzone = tf.timezone_at(lng=lon, lat=lat)
    timezone = pytz.timezone(tzone)
    if 'utc_offset_hours' not in data.keys():
        # HACK: America/Inuvik is giving an offset of 0 when applied directly, but says -6 otherwise
        run_start = datetime.datetime.strptime(
            f"{data['job_date']}{data['job_time']}", "%Y%m%d%H%M")
        utcoffset = timezone.utcoffset(run_start)
        utcoffset_hours = utcoffset.total_seconds() / 60 / 60
        data['utcoffset_hours'] = utcoffset_hours
    if 'wx' not in data.keys():
        ffmc_old = data['ffmc_old']
        dmc_old = data['dmc_old']
        dc_old = data['dc_old']
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
        # HACK: just get something for now
        have_noon = [x.date() for x in df_wx_fire[df_wx_fire['HR'] == 12]['TIMESTAMP']]
        df_wx_fire = df_wx_fire[[x.date() in have_noon for x in df_wx_fire['TIMESTAMP']]]
        # noon = datetime.datetime.fromordinal(today.toordinal()) + datetime.timedelta(hours=12)
        # df_wx_fire = df_wx_fire[df_wx_fire['TIMESTAMP'] >= noon].reset_index()[cols]
        df_fwi = NG_FWI.hFWI(
            df_wx_fire,
            utcoffset_hours,
            ffmc_old,
            dmc_old,
            dc_old)
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
        file_wx = "wx.csv"
        df_wx.round(2).to_csv(os.path.join(dir_fire, file_wx), index=False, quoting=False)
        start_time = min(df_wx['Date']).tz_localize(timezone)
        # HACK: don't start right at midnight because the hour before is missing
        if (6 > start_time.hour):
            start_time = start_time.replace(hour=6, minute=0, second=0)
        days_available = (df_wx['Date'].max() - df_wx['Date'].min()).days
        max_days = data['max_days']
        want_dates = WANT_DATES
        if max_days is not None:
            want_dates = [x for x in want_dates if x <= max_days]
        offsets = [x for x in want_dates if x <= days_available]
        data["start_time"] = start_time.isoformat()
        data["offsets"] = offsets
        data["wx"] = file_wx
    with open(os.path.join(dir_fire, FILE_SIM), "w") as f:
        json.dump(data, f)
    # at this point everything should be in the sim file, and we can just run it
    result = tbd.run_fire_from_folder(dir_fire, dir_current)
    t = result['sim_time']
    if t is not None:
        logging.debug("Took {}s to run simulations".format(t))
    return result


# dir_fires = "/home/bfdata/affes/latest"
def run_all_fires(dir_fires=None, max_days=None):
    t0 = timeit.default_timer()
    DIR_ROOT = "/home/bfdata"
    run_start = datetime.datetime.now()
    today = run_start.date()
    yesterday = today - datetime.timedelta(days=1)
    # NOTE: use NAD 83 / Statistics Canada Lambert since it should do well with distances
    crs = 'EPSG:3347'
    proj = pyproj.CRS(crs)
    run_prefix = 'm3' if dir_fires is None else dir_fires.replace('\\', '/').strip('/').replace('/', '_')
    run_id = run_start.strftime("%Y%m%d%H%M")
    run_name = f"{run_prefix}_{run_id}"
    dir_out = ensure_dir(os.path.join(DIR_ROOT, run_name))
    # "current" results folder to update based on new run data
    dir_current = os.path.join(tbd.DIR_OUTPUT, f"current_{run_prefix}")
    # HACK: want to keep all the runs and not just overwrite them, so use subfolder
    dir_current = os.path.join(dir_current, run_id)
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
    # we only want stations that have indices
    for index in ['ffmc', 'dmc', 'dc']:
        df_wx_cwfis = df_wx_cwfis[~np.isnan(df_wx_cwfis[index])]
    df_wx_cwfis_wgs = df_wx_cwfis.to_crs(proj)
    df_wx = df_wx_cwfis_wgs
    # cut out the row as a DataFrame still so we can use crs and centroid
    df_by_fire = [df_fires.iloc[fire_id:(fire_id + 1)] for fire_id in range(len(df_fires))]
    dirs_fire = []
    for df_fire in tqdm(df_by_fire, desc='Separating fires', leave=False):
        fire_name = df_fire.iloc[0]['fire_name']
        pt_centroid = df_fire.centroid.iloc[0]
        dists = df_wx.distance(pt_centroid)
        # figure out startup indices yesterday
        df_wx_actual = df_wx[dists == min(dists)]
        ffmc_old, dmc_old, dc_old = df_wx_actual.iloc[0][['ffmc', 'dmc', 'dc']]
        dir_fire = make_run_fire(dir_out, df_fire, run_start, ffmc_old, dmc_old, dc_old, max_days)
        dirs_fire.append(dir_fire)
    # small limit due to amount of disk access
    # num_threads = int(min(len(df_fires), multiprocessing.cpu_count() / 4))
    # HACK: weird mess to ensure thread has proper objects to call function
    for_what = list(zip(dirs_fire, [dir_current] * len(dirs_fire)))
    sim_results = tqdm_pool.pmap(do_run_fire, for_what, desc="Running simulations")
    dates_out = []
    results = {}
    sim_time = 0
    for result in sim_results:
        fire_name = result['fire_name']
        results[fire_name] = result
        if result['sim_finished']:
            sim_time += result['sim_time']
            dates_out = dates_out + [x for x in result['dates_out']]
    logging.info("Done")
    t1 = timeit.default_timer()
    totaltime = (t1 - t0)
    logging.info("Took %ds to run fires", totaltime)
    logging.info("Successful simulations used %ds", sim_time)
    return dir_out, dir_current, results, dates_out, totaltime



# # FIX: need to update to work with new directory structure and return values
# def merge_outputs(dir_out):
#     for fire_name in [x for x in os.listdir(dir_out) if os.path.isdir(os.path.join(dir_out, x))]:
#         dir_fire = os.path.join(dir_out, fire_name)
#         print(dir_fire)
#         dir_out, log_name, dates_out = tbd.run_fire_from_folder(dir_fire)
#     merge_dirs(dir_current)


if __name__ == "__main__":
    max_days = int(sys.argv[1]) if len(sys.argv) > 1 else None
    dir_fires = sys.argv[2] if len(sys.argv) > 2 else None
    dir_out, dir_current, results, dates_out, totaltime = run_all_fires(dir_fires, max_days)
    # simtimes, totaltime, dates = run_all_fires()
    n = len(results)
    if n > 0:
        logging.info(
            "Total of {} fires took {}s - average time is {}s".format(
                n, totaltime, totaltime / n
            )
        )
        merge_dirs(dir_current)
