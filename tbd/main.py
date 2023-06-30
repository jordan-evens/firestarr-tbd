import os
import sys
import logging
import math

# makes groups that are too big because it joins mutiple groups into a chain
# DEFAULT_GROUP_DISTANCE_KM = 60
# also too big
# DEFAULT_GROUP_DISTANCE_KM = 40
DEFAULT_GROUP_DISTANCE_KM = 20
# DEFAULT_NUM_DAYS = 3
# DEFAULT_NUM_DAYS = 7
DEFAULT_NUM_DAYS = 14

DEFAULT_FILE_LOG_LEVEL = logging.DEBUG
# DEFAULT_FILE_LOG_LEVEL = logging.INFO

# FORMAT_OUTPUT = "COG"
FORMAT_OUTPUT = "GTiff"

USE_CWFIS = False

sys.path.append("../util")
from log import *

DIR_LOG = "./logs"
os.makedirs(DIR_LOG, exist_ok=True)
LOG_MAIN = add_log_rotating(
    os.path.join(DIR_LOG, "firestarr.log"), level=DEFAULT_FILE_LOG_LEVEL
)
logging.info("Starting main.py")
CRS_LAMBERT = "EPSG:3347"
CRS_DEFAULT = CRS_LAMBERT

import urllib.request as urllib2
from bs4 import BeautifulSoup
import pandas as pd
import datetime

import common
from common import ensure_dir
from common import list_dirs
import publish
import model_data
import gis
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
import osgeo_utils
from gdal_merge_max import gdal_merge_max

# import osgeo_utils.gdal_merge as gm
import osgeo_utils.gdal_retile as gr
import osgeo_utils.gdal_calc as gdal_calc
import itertools
import json
import pytz
import pyproj
import subprocess

sys.path.append("./cffdrs-ng")
import NG_FWI

import tbd
from tbd import FILE_SIM

DIR_DATA = "../data"
DIR_SIMS = os.path.join(DIR_DATA, "sims")
CREATION_OPTIONS = [
    "COMPRESS=LZW",
    "TILED=YES",
    "BLOCKSIZE=512",
    "OVERVIEWS=AUTO",
    "NUM_THREADS=ALL_CPUS",
]
CRS_OUTPUT = 3978

# CRS_NAD83 = 4269
# CRS_NAD83_CSRS = 4617
# want a projection that's NAD83 based, project, and units are degrees
# CRS = "ESRI:102002"
CRS_SIMINPUT = 4269
PLACEHOLDER_TITLE = "__TITLE__"
FILE_HTML = os.path.join(DIR_DATA, "output/firestarr.html")
WANT_DATES = [1, 2, 3, 7, 14]
KM_TO_M = 1000
# HACK: FIX: assume everything is this year
YEAR = datetime.date.today().year


def getPage(url):
    logging.debug("Opening {}".format(url))
    # query the website and return the html to the variable 'page'
    page = urllib2.urlopen(url)
    # parse the html using beautiful soup and return
    return BeautifulSoup(page, "html.parser")


# ###################
# import numpy as np
# import rasterio
# from rasterio.warp import calculate_default_transform, reproject, Resampling

# def do_merge(file_out, files, dst_crs=CRS_DEFAULT):
#     with rasterio.open('path/test.tif') as src:
#         transform, width, height = calculate_default_transform(
#             src.crs, dst_crs, src.width, src.height, *src.bounds)
#         kwargs = src.meta.copy()
#         kwargs.update({
#             'crs': dst_crs,
#             'transform': transform,
#             'width': width,
#             'height': height
#         })
#         with rasterio.open('path/test_wgs84.tif', 'w', **kwargs) as dst:
#             for i in range(1, src.count + 1):
#                 reproject(
#                     source=rasterio.band(src, i),
#                     destination=rasterio.band(dst, i),
#                     src_transform=src.transform,
#                     src_crs=src.crs,
#                     dst_transform=transform,
#                     dst_crs=dst_crs,
#                     resampling=Resampling.nearest)
# ###################


def merge_dir(dir_in, run_id, force=False, creation_options=CREATION_OPTIONS):
    logging.info("Merging {}".format(dir_in))
    # HACK: for some reason output tiles were both being called 'probability'
    # import importlib
    from osgeo import gdal
    use_exceptions = gdal.GetUseExceptions()
    # HACK: if exceptions are on then gdal_merge throws one
    gdal.DontUseExceptions()
    # importlib.reload(gr)
    # TILE_SIZE = str(1024)
    co = list(
        itertools.chain.from_iterable(map(lambda x: ["-co", x], creation_options))
    )
    dir_base = os.path.dirname(dir_in)
    dir_parent = os.path.dirname(dir_base)
    # dir_type = os.path.basename(dir_base)
    # want to put probability and perims together
    dir_out = common.ensure_dir(
        os.path.join(
            dir_parent,
            "combined",
            os.path.basename(dir_in)
        )
    )
    files_by_for_what = {}
    for region in list_dirs(dir_in):
        dir_region = os.path.join(dir_in, region)
        if os.path.isdir(dir_region):
            for for_what in list_dirs(dir_region):
                dir_for_what = os.path.join(dir_region, for_what)
                files_by_for_what[for_what] = files_by_for_what.get(for_what, []) + [
                    os.path.join(dir_for_what, x)
                    for x in sorted(os.listdir(dir_for_what))
                    if x.endswith(".tif")
                ]
    ymd_origin = os.path.basename(dir_in)
    # HACK: need to worry about local vs UTC time here
    # date_origin = datetime.datetime.strptime(ymd_origin, '%Y%m%d')
    dirs_what = [os.path.basename(for_what) for for_what in files_by_for_what.keys()]
    for_dates = [
        datetime.datetime.strptime(_, "%Y%m%d") for _ in dirs_what if "perim" != _
    ]
    date_origin = min(for_dates)
    # for_what, files = list(files_by_for_what.items())[-2]
    for for_what, files in tqdm(files_by_for_what.items(),
                                desc=f"Merging {dir_in}",
                                leave=False):
        dir_in_for_what = os.path.basename(for_what)
        # HACK: forget about tiling and just do what we need now
        if "perim" == dir_in_for_what:
            dir_for_what = "perim"
            date_cur = for_dates[0]
        else:
            date_cur = datetime.datetime.strptime(dir_in_for_what, "%Y%m%d")
            offset = (date_cur - date_origin).days + 1
            dir_for_what = f"day_{offset:02d}"
        dir_crs = ensure_dir(os.path.join(dir_parent,
                               "reprojected",
                               dir_in_for_what))
        files_crs = []
        for f in tqdm(files, desc=f"Reprojecting for {dir_in_for_what}", leave=False):
            f_crs = os.path.join(dir_crs, os.path.basename(f))
            files_crs.append(f_crs)
            gis.project_raster(f,
                               f_crs,
                               resolution=100,
                               nodata=0,
                               crs=f"EPSG:{CRS_OUTPUT}")
        file_root = os.path.join(dir_out, f"firestarr_{run_id}_{dir_for_what}_{date_cur.strftime('%Y%m%d')}")
        file_tmp = f"{file_root}_tmp.tif"
        file_base = f"{file_root}.tif"
        # argv = (["", "-a_nodata", "-1"]
        #     + co
        #     + ["-o", file_tmp]
        #     + files_crs)

        gdal_merge_max(
            (
                ["",
                 #"-n", "0",
                 "-a_nodata", "-1"]
                + co
                + ["-o", file_tmp]
                + files_crs
            )
        )
        if "GTiff" == FORMAT_OUTPUT:
            shutil.move(file_tmp, file_base)
        else:
            # HACK: reproject should basically just be copy?
            # convert to COG
            gis.project_raster(file_tmp,
                            file_base,
                            nodata=-1,
                            resolution=100,
                            format=FORMAT_OUTPUT,
                            crs=f"EPSG:{CRS_OUTPUT}",
                            options=creation_options + [
                                # shouldn't need much precision just for web display
                                "NBITS=16",
                                # shouldn't need alpha?
                                #"ADD_ALPHA=NO",
                                #"SPARSE_OK=TRUE",
                                "PREDICTOR=YES"
                                ]
                                )
            os.remove(file_tmp)
    if use_exceptions:
        gdal.UseExceptions()
    return dir_out


def merge_dirs(dir_input=None, dates=None):
    # NOTE: do_tile takes hours if run for the entire country with all polygons
    if dir_input is None:
        dir_default = os.path.join(tbd.DIR_OUTPUT, "current_m3")
        dir_input = os.path.join(
            dir_default,
            [x for x in list_dirs(dir_default) if os.path.isdir(
                os.path.join(dir_default, x, "initial"))][-1])
        logging.info("Defaulting to directory %s", dir_input)
    # expecting dir_input to be a path ending in a runid of form '%Y%m%d%H%M'
    dir_initial = os.path.join(dir_input, "initial")
    run_id = os.path.basename(dir_input)
    results = []
    # this expects folders to be '%Y%m%d' for start day for runs
    # NOTE: should really only have one folder in here if we're saving to dir_input for each run
    for d in sorted(list_dirs(dir_initial)):
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


def get_fires_active(dir_out, status_include=None, status_omit=["OUT"]):
    str_year = str(YEAR)
    def fix_name(name):
        if isinstance(name, str) or not (name is None or np.isnan(name)):
            s = str(name).replace("-", "_")
            if s.startswith(str_year):
                s = s[len(str_year) :]
            if s.endswith(str_year):
                s = s[:-len(str_year)]
            s = s.strip("_")
            return s
        return ""
    # this isn't an option, because it filters out fires
    # df_dip = model_data.get_fires_dip(dir_out, status_ignore=None)
    df_ciffc, ciffc_json = model_data.get_fires_ciffc(dir_out, status_ignore=None)
    if USE_CWFIS:
        df_m3, m3_json = model_data.get_fires_m3(dir_out)
    else:
        df_m3 = model_data.get_m3_download(dir_out, df_ciffc)
    df_m3["guess_id"] = df_m3["guess_id"].apply(fix_name)
    df_m3["fire_name"] = df_m3.apply(
        lambda x: fix_name(x["guess_id"] or x["id"]), axis=1
    )
    df_ciffc["fire_name"] = df_ciffc["field_agency_fire_id"].apply(fix_name)
    df_ciffc_non_geo = df_ciffc.loc[:]
    del df_ciffc_non_geo["id"]
    del df_ciffc_non_geo["geometry"]
    df_matched = pd.merge(
        df_m3, df_ciffc_non_geo, left_on="fire_name", right_on="fire_name"
    )
    # fires that were matched but don't join with ciffc
    missing = [
        x for x in list(set(np.unique(df_m3.guess_id)) - set(df_matched.fire_name)) if x
    ]
    if 0 < len(missing):
        logging.error(
            "M3 guessed polygons for %d fires that aren't listed on ciffc: %s",
            len(missing),
            str(missing),
        )
    # Only want to run matched polygons, and everything else plus ciffc points
    id_matched = df_matched.id
    id_m3 = df_m3.id
    id_diff = list(set(id_m3) - set(id_matched))
    df_matched = df_matched.set_index(["id"])
    df_unmatched = df_m3.set_index(["id"]).loc[id_diff]
    logging.info("M3 has %d polygons that are not tied to a fire", len(df_unmatched))
    if status_include:
        df_matched = df_matched[df_matched.field_stage_of_control_status.isin(status_include)]
        logging.info("M3 has %d polygons that are tied to %s fires", len(df_matched), status_include)
    if status_omit:
        df_matched = df_matched[~df_matched.field_stage_of_control_status.isin(status_omit)]
        logging.info("M3 has %d polygons that aren't tied to %s fires", len(df_matched), status_omit)
    df_poly_m3 = pd.concat([df_matched, df_unmatched])
    logging.info("Using %d polygons as inputs", len(df_poly_m3))
    # now find any fires that weren't matched to a polygon
    diff_ciffc = list((set(df_ciffc.fire_name) - set(df_matched.fire_name)))
    df_ciffc_pts = df_ciffc.set_index(["fire_name"]).loc[diff_ciffc]
    if status_include:
        df_ciffc_pts = df_ciffc_pts[df_ciffc_pts.field_stage_of_control_status.isin(status_include)]
    if status_omit:
        df_ciffc_pts = df_ciffc_pts[~df_ciffc_pts.field_stage_of_control_status.isin(status_omit)]
    logging.info(
        "Found %d fires that aren't matched with polygons", len(df_ciffc_pts)
    )
    df_poly = df_poly_m3.reset_index()[["fire_name", "geometry"]]
    def area_to_radius(a):
        return math.sqrt(a / math.pi)
    df_ciffc_pts = df_ciffc_pts.to_crs(df_poly.crs)
    # HACK: put in circles of proper area if no perimeter
    df_ciffc_pts['radius'] = df_ciffc_pts['field_fire_size'].apply(lambda x: max(0.1, area_to_radius(max(0, x))))
    df_ciffc_pts['geometry'] = df_ciffc_pts.apply(lambda x: x.geometry.buffer(x.radius), axis=1)
    df_pts = df_ciffc_pts.reset_index()[["fire_name", "geometry"]]
    df_fires = pd.concat([df_pts, df_poly])
    return df_fires


def separate_points(f):
    pts = [x for x in f if x.geom_type == "Point"]
    polys = [x for x in f if x.geom_type != "Point"]
    return pts, polys


def group_fires(df_fires, group_distance_km=DEFAULT_GROUP_DISTANCE_KM):
    group_distance = group_distance_km * KM_TO_M
    crs = df_fires.crs

    def to_gdf(d):
        return gpd.GeoDataFrame(geometry=d, crs=crs)

    groups = to_gdf(df_fires["geometry"])
    pts, polys = separate_points(groups.geometry)
    df_polys = to_gdf(polys)
    # we can check if any points are within polygons, and throw out any that are
    pts_keep = [p for p in pts if not np.any(df_polys.contains(p))]
    # p_check = [to_gdf([x]) for x in (pts_keep + polys)]
    p_check = to_gdf(pts_keep + polys)
    p = p_check.iloc[:1]
    p_check = p_check.iloc[1:]
    # just check polygon proximity to start
    # logging.info("Grouping polygons")
    with tqdm(desc="Grouping fires", total=len(p_check), leave=False) as tq:
        p_done = []
        while 0 < len(p_check):
            n_prev = len(p_check)
            compare_to = to_gdf(p_check.geometry)
            # distances should be in meters
            compare_to["dist"] = compare_to.apply(
                lambda x: min(x["geometry"].distance(y) for y in p.geometry), axis=1
            )
            p_nearby = compare_to[compare_to.dist <= group_distance]
            if 0 < len(p_nearby):
                group = list(p.geometry) + list(p_nearby.geometry)
                g_pts, g_polys = separate_points(group)
                g_dissolve = list(to_gdf(g_polys).dissolve().geometry)
                p = to_gdf(g_pts + g_dissolve)
                # need to check whatever was far away
                p_check = compare_to[compare_to.dist > group_distance][["geometry"]]
            else:
                # nothing close to this, so done with it
                p_done.append(p)
                p = p_check.iloc[:1]
                p_check = p_check.iloc[1:]
            tq.update(n_prev - len(p_check))
    tq.update(1)
    merged = [p] + p_done
    # NOTE: year should not be relevant, because we just care about the projection, not the data
    zone_rasters = gis.find_raster_meridians(YEAR)
    zone_rasters = {k: v for k, v in zone_rasters.items() if not v.endswith("_5.tif")}

    def find_best_zone_raster(lon):
        best = 9999
        for i in zone_rasters.keys():
            if abs(best - lon) > abs(i - lon):
                best = i
        return zone_rasters[best]

    for i in tqdm(range(len(merged)), desc="Naming groups", leave=False):
        df_group = merged[i]
        # HACK: can't just convert to lat/long crs and use centroids from that because it causes a warning
        df_dissolve = df_group.dissolve()
        centroid = df_dissolve.centroid.to_crs(CRS_SIMINPUT).iloc[0]
        df_group["lon"] = centroid.x
        df_group["lat"] = centroid.y
        # # df_fires = df_fires.to_crs(CRS)
        # df_fires = df_fires.sort_values(['area_calc'])
        # HACK: name based on UTM coordinates
        r = find_best_zone_raster(centroid.x)
        zone_wkt = gis.GetSpatialReference(r).ExportToWkt()
        zone = int(os.path.basename(r).split("_")[1])
        # HACK: just use gpd since it's easier
        centroid_utm = (
            gpd.GeoDataFrame(geometry=[centroid], crs=CRS_SIMINPUT)
            .to_crs(zone_wkt)
            .iloc[0]
            .geometry
        )
        # this is too hard to follow
        # df_group['fire_name'] = f"{zone}N_{int(centroid_utm.x)}_{int(centroid_utm.y)}"
        BM_MULT = 10000
        easting = int((centroid_utm.x) // BM_MULT)
        northing = int((centroid_utm.y) // BM_MULT)
        basemap = easting * 1000 + northing
        # df_group['utm_zone'] = zone
        # df_group['basemap'] = int(f"{easting:02d}{northing:03d}")
        n_or_s = "N" if centroid.y >= 0 else "S"
        df_group["fire_name"] = f"{zone}{n_or_s}_{basemap}"
        # it should be impossible for 2 groups to be in the same basemap, because they are 10km?
        merged[i] = df_group
    results = pd.concat(merged)
    logging.info("Created %d groups", len(results))
    return results


# def group_fires(df_fires, group_distance_km=10):
#     group_distance = group_distance_km * KM_TO_M
#     crs = df_fires.crs
#     groups = gpd.GeoDataFrame(geometry=df_fires['geometry'], crs=crs)
#     pts = [x for x in groups.geometry if x.geom_type == 'Point']
#     polys = [x for x in groups.geometry if x.geom_type != 'Point']
#     df_polys = gpd.GeoDataFrame(geometry=polys, crs=crs)
#     # we can check if any points are within polygons, and throw out any that are
#     pts_keep = [p for p in pts if not np.any(df_polys.contains(p))]
#     # just check polygon proximity to start
#     # logging.info("Grouping polygons")
#     with tqdm(desc="Grouping polygons", total=len(polys), leave=False) as tq:
#         p_done = []
#         while 1 < len(polys):
#             p = polys.pop(0)
#             compare_to = gpd.GeoDataFrame(geometry=polys, crs=crs)
#             # distances should be in meters
#             compare_to['dist'] = compare_to.geometry.distance(p)
#             p_nearby = compare_to[compare_to.dist <= group_distance]
#             if 0 < len(p_nearby):
#                 p_far = compare_to[compare_to.dist > group_distance]
#                 group = [p] + list(p_nearby.geometry)
#                 tq.update(len(group))
#                 # should be able to dissolve all polygons, but need to keep distinct points
#                 # so do points later
#                 p = gpd.GeoDataFrame(geometry=group, crs=crs).dissolve().geometry[0]
#                 polys = [p] + list(p_far.geometry)
#             else:
#                 tq.update(1)
#                 # nothing close to this, so done with it
#                 p_done.append(p)
#     # polys should just be 1 thing if we had any polygons
#     df_polys = gpd.GeoDataFrame(geometry=p_done, crs=crs)
#     df_pts = gpd.GeoDataFrame(geometry=pts_keep, crs=crs)
#     df_closest = df_pts.sjoin_nearest(df_polys, how="left", max_distance=group_distance)
#     results = []
#     for i in range(len(df_polys)):
#         p = df_polys.iloc[i].geometry
#         pts = df_closest[df_closest.index_right == i]
#         group = [p] + list(pts.geometry)
#         results.append(gpd.GeoDataFrame(geometry=group, crs=crs))
#     df_remaining = df_closest[np.isnan(df_closest.index_right)]
#     results.extend([gpd.GeoDataFrame(geometry=[df_remaining.iloc[i].geometry], crs=crs) for i in range(len(df_remaining))])
#     for i in range(len(results)):
#         df_group = results[i]
#         # HACK: can't just convert to lat/long crs and use centroids from that because it causes a warning
#         df_dissolve = df_group.dissolve()
#         centroid = df_dissolve.centroid.to_crs(CRS).iloc[0]
#         df_group['lon'] = centroid.x
#         df_group['lat'] = centroid.y
#         df_group['area_calc'] = df_group.area
#         # # df_fires = df_fires.to_crs(CRS)
#         # df_fires = df_fires.sort_values(['area_calc'])
#         # HACK: name based on UTM coordinates
#         r = gis.find_best_raster(centroid.x, YEAR)
#         zone = gis.GetSpatialReference(r).ExportToWkt()
#         zone_string = '_'.join(os.path.basename(r).split('_')[1:]).split('.')[0]
#         # HACK: just use gpd since it's easier
#         centroid_utm = gpd.GeoDataFrame(geometry=[centroid], crs=CRS).to_crs(zone).iloc[0].geometry
#         df_group['fire_name'] = f"{zone_string}N_{int(centroid_utm.x)}_{int(centroid_utm.y)}"
#         df_group['utm_zone'] = float(zone_string)
#         BM_MULT = 10000
#         easting = int((centroid_utm.x) // BM_MULT)
#         northing = int((centroid_utm.y) // BM_MULT)
#         df_group['basemap'] = int(f"{easting:02d}{northing:03d}")
#         # it should be impossible for 2 groups to be in the same basemap, because they are 10km?
#         results[i] = df_group
#     results = pd.concat(results)
#     return results


def get_fires_folder(dir_fires, crs=CRS_DEFAULT):
    proj = pyproj.CRS(crs)
    df_fires = None
    for root, dirs, files in os.walk(dir_fires):
        for f in [x for x in files if x.lower().endswith(".shp")]:
            file_shp = os.path.join(root, f)
            df_fire = gpd.read_file(file_shp).to_crs(proj)
            df_fires = pd.concat([df_fires, df_fire])
    df_fires["fire_name"] = df_fires["FIRENUMB"]
    return df_fires


# def prepare_run_fire(dir_out, run_start, tf, df_fire, df_wx, max_days=None):
# def run_fire(dir_out, run_start, tf, df_fire, df_wx, dir_current, max_days=None):
def make_run_fire(
    dir_out, df_fire, run_start, ffmc_old, dmc_old, dc_old, max_days=None
):
    if 1 != len(np.unique(df_fire["fire_name"])):
        raise RuntimeError("Expected exactly one fire_name run_fire()")
    fire_name, lat, lon = df_fire[["fire_name", "lat", "lon"]].iloc[0]
    dir_fire = ensure_dir(os.path.join(dir_out, fire_name))
    logging.debug("Saving %s to %s", fire_name, dir_fire)
    file_fire = os.path.join(dir_fire, "{}_NAD1983.geojson".format(fire_name))
    df_fire.to_file(file_fire)
    data = {
        # UTC time
        "job_date": run_start.strftime("%Y%m%d"),
        "job_time": run_start.strftime("%H%M"),
        "ffmc_old": ffmc_old,
        "dmc_old": dmc_old,
        "dc_old": dc_old,
        # HACK: FIX: need to actually figure this out
        "apcp_prev": 0,
        "lat": lat,
        "lon": lon,
        "perim": os.path.basename(file_fire),
        "dir_out": os.path.join(dir_fire, "firestarr"),
        "fire_name": fire_name,
        "max_days": max_days,
    }
    with open(os.path.join(dir_fire, FILE_SIM), "w") as f:
        json.dump(data, f)
    return dir_fire


def do_prep_fire(dir_fire):
    # load and update the configuration with more data
    with open(os.path.join(dir_fire, FILE_SIM)) as f:
        data = json.load(f)
    lat = data["lat"]
    lon = data["lon"]
    # need for offset and wx
    import timezonefinder

    tf = timezonefinder.TimezoneFinder()
    tzone = tf.timezone_at(lng=lon, lat=lat)
    timezone = pytz.timezone(tzone)
    if "utc_offset_hours" not in data.keys():
        # UTC time
        # HACK: America/Inuvik is giving an offset of 0 when applied directly, but says -6 otherwise
        run_start = datetime.datetime.strptime(
            f"{data['job_date']}{data['job_time']}", "%Y%m%d%H%M"
        )
        utcoffset = timezone.utcoffset(run_start)
        utcoffset_hours = utcoffset.total_seconds() / 60 / 60
        data["utcoffset_hours"] = utcoffset_hours
    if "wx" not in data.keys():
        ffmc_old = data["ffmc_old"]
        dmc_old = data["dmc_old"]
        dc_old = data["dc_old"]
        try:
            df_wx_spotwx = model_data.get_wx_ensembles(lat, lon)
        except KeyboardInterrupt as ex:
            raise ex
        except Exception as ex:
            # logging.fatal("Could not get weather for %s", dir_fire)
            # logging.fatal(ex)
            return ex
        df_wx_filled = model_data.wx_interpolate(df_wx_spotwx)
        df_wx_fire = df_wx_filled.rename(
            columns={"datetime": "TIMESTAMP", "precip": "PREC"}
        ).loc[:]
        # HACK: just do the math for now, but don't apply a timezone
        df_wx_fire.loc[:, "TIMESTAMP"] = df_wx_fire["TIMESTAMP"] + utcoffset
        df_wx_fire.columns = [s.upper() for s in df_wx_fire.columns]
        df_wx_fire.loc[:, "YR"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].year, axis=1
        )
        df_wx_fire.loc[:, "MON"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].month, axis=1
        )
        df_wx_fire.loc[:, "DAY"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].day, axis=1
        )
        df_wx_fire.loc[:, "HR"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].hour, axis=1
        )
        # cols = df_wx_fire.columns
        # HACK: just get something for now
        have_noon = [x.date() for x in df_wx_fire[df_wx_fire["HR"] == 12]["TIMESTAMP"]]
        df_wx_fire = df_wx_fire[
            [x.date() in have_noon for x in df_wx_fire["TIMESTAMP"]]
        ]
        # # HACK: not 0 indexed if we don't reset_index()
        # df_wx_fire =  df_wx_fire.reset_index(drop=True)
        # noon = datetime.datetime.fromordinal(today.toordinal()) + datetime.timedelta(hours=12)
        # df_wx_fire = df_wx_fire[df_wx_fire['TIMESTAMP'] >= noon].reset_index()[cols]
        # NOTE: expects weather in localtime, but uses utcoffset to figure out local sunrise/sunset
        df_fwi = NG_FWI.hFWI(df_wx_fire, utcoffset_hours, ffmc_old, dmc_old, dc_old)
        # HACK: get rid of missing values at end of period
        df_fwi = df_fwi[~np.isnan(df_fwi["FWI"])].reset_index(drop=True)
        # COLUMN_SYNONYMS = {'WIND': 'WS', 'RAIN': 'PREC', 'YEAR': 'YR', 'HOUR': 'HR'}
        df_wx = df_fwi.rename(
            columns={
                "TIMESTAMP": "Date",
                "ID": "Scenario",
                "RAIN": "PREC",
                "WIND": "WS",
            }
        )
        df_wx = df_wx[
            [
                "Scenario",
                "Date",
                "PREC",
                "TEMP",
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
        df_wx.round(2).to_csv(
            os.path.join(dir_fire, file_wx), index=False, quoting=False
        )
        # HACK: make sure we're using the UTC date as the start day
        start_time = min(
            df_wx[df_wx["Date"].apply(lambda x: x.date()) >= run_start.date()]["Date"]
        ).tz_localize(timezone)
        # HACK: don't start right at start because the hour before is missing
        start_time += datetime.timedelta(hours=1)
        # if (6 > start_time.hour):
        #     start_time = start_time.replace(hour=6, minute=0, second=0)
        days_available = (df_wx["Date"].max() - df_wx["Date"].min()).days
        max_days = data["max_days"]
        want_dates = WANT_DATES
        if max_days is not None:
            want_dates = [x for x in want_dates if x <= max_days]
        offsets = [x for x in want_dates if x <= days_available]
        data["start_time"] = start_time.isoformat()
        data["offsets"] = offsets
        data["wx"] = file_wx
    with open(os.path.join(dir_fire, FILE_SIM), "w") as f:
        json.dump(data, f)
    return dir_fire


def do_run_fire(for_what):
    dir_fire, dir_current, verbose = for_what
    # HACK: in case do_prep_fire() failed
    if isinstance(dir_fire, Exception):
        return dir_fire
    try:
        with open(os.path.join(dir_fire, FILE_SIM)) as f:
            data = json.load(f)
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        logging.warning(ex)
        return ex
    # at this point everything should be in the sim file, and we can just run it
    try:
        result = tbd.run_fire_from_folder(dir_fire, dir_current, verbose=verbose)
        t = result["sim_time"]
        if t is not None:
            logging.debug("Took {}s to run simulations".format(t))
        result["failed"] = False
        return result
    except Exception as ex:
        logging.warning(ex)
        return ex
        # data['sim_time'] = None
        # data['dates_out'] = None
        # data['sim_finished'] = False
        # data['failed'] = True
        # return data


# make this a function so we can call it during or after loop
def check_failure(dir_fire, result, stop_on_any_failure):
    if isinstance(result, Exception):
        logging.warning("Failed to get weather for %s", dir_fire)
        if isinstance(result, common.ParseError):
            file_content = os.path.join(dir_fire, "exception_content.out")
            with open(file_content, "w") as f_ex:
                # HACK: this is just where it ends up
                content = result.args[0][0]
                f_ex.write(str(content))
            with open(os.path.join(dir_fire, "exception_trace.out"), "w") as f_ex:
                f_ex.writelines(result.trace)
        else:
            with open(os.path.join(dir_fire, "exception.out"), "w") as f_ex:
                f_ex.write(str(result))
        if stop_on_any_failure:
            raise result
        return 1
    return 0


def do_prep_and_run_fire(for_what):
    dir_fire, dir_current, verbose = for_what
    dir_ready = do_prep_fire(dir_fire)
    return do_run_fire((dir_ready, dir_current, verbose))


# dir_fires = "/appl/data/affes/latest"
def run_all_fires(dir_fires=None, max_days=None, stop_on_any_failure=False):
    t0 = timeit.default_timer()
    # UTC time
    run_start = datetime.datetime.now()
    run_prefix = (
        "m3"
        if dir_fires is None
        else dir_fires.replace("\\", "/").strip("/").replace("/", "_")
    )
    run_id = run_start.strftime("%Y%m%d%H%M")
    run_name = f"{run_prefix}_{run_id}"
    dir_out = ensure_dir(os.path.join(DIR_SIMS, run_name))
    log_run = add_log_file(
        os.path.join(dir_out, "firestarr.txt"), level=DEFAULT_FILE_LOG_LEVEL
    )
    logging.info("Starting run for %s", dir_out)
    # UTC time
    today = run_start.date()
    yesterday = today - datetime.timedelta(days=1)
    # NOTE: use NAD 83 / Statistics Canada Lambert since it should do well with distances
    crs = CRS_DEFAULT
    proj = pyproj.CRS(crs)
    # keep a copy of the settings for reference
    shutil.copy("/appl/tbd/settings.ini", os.path.join(dir_out, "settings.ini"))
    # also keep binary instead of trying to track source
    shutil.copy("/appl/tbd/tbd", os.path.join(dir_out, "tbd"))
    # "current" results folder to update based on new run data
    dir_current = os.path.join(tbd.DIR_OUTPUT, f"current_{run_prefix}")
    # HACK: want to keep all the runs and not just overwrite them, so use subfolder
    dir_current = os.path.join(dir_current, run_id)
    # only care about startup indices
    if USE_CWFIS:
        df_wx_startup = model_data.get_wx_cwfis(dir_out, [today, yesterday], indices="ffmc,dmc,dc")
    else:
        df_wx_startup = model_data.get_wx_cwfis_download(dir_out, [today, yesterday])
    # we only want stations that have indices
    for index in ["ffmc", "dmc", "dc"]:
        df_wx_startup = df_wx_startup[~np.isnan(df_wx_startup[index])]
    df_wx_startup_wgs = df_wx_startup.to_crs(proj)
    df_wx = df_wx_startup_wgs
    if dir_fires is None:
        df_fires_active = get_fires_active(dir_out)
        df_fires_groups = group_fires(df_fires_active)
        df_fires = df_fires_groups
    else:
        df_fires = get_fires_folder(dir_fires, crs)
        df_fires = df_fires.to_crs(crs)
        # HACK: can't just convert to lat/long crs and use centroids from that because it causes a warning
        centroids = df_fires.centroid.to_crs(CRS_SIMINPUT)
        df_fires["lon"] = centroids.x
        df_fires["lat"] = centroids.y
        # df_fires = df_fires.to_crs(CRS)
    # cut out the row as a DataFrame still so we can use crs and centroid
    # df_by_fire = [df_fires.iloc[fire_id:(fire_id + 1)] for fire_id in range(len(df_fires))]
    file_bounds = common.BOUNDS['bounds']
    if file_bounds:
        logging.info(f"Using groups in boundaries defined by {file_bounds}")
        bounds = gpd.read_file(file_bounds).to_crs(df_fires.crs)
        # df_fires = df_fires.reset_index(drop=True).set_index(['fire_name'])
        df_fires = df_fires[df_fires.intersects(bounds.dissolve().iloc[0].geometry)]
    # fire_areas = df_fires.dissolve(by=['fire_name']).area.sort_values()
    # NOTE: if we do biggest first then shorter ones can fill in gaps as that one
    # takes the longest to run?
    # FIX: consider sorting by startup indices or overall DSR for period instead?
    fire_areas = df_fires.dissolve(by=["fire_name"]).area.sort_values(ascending=False)
    dirs_fire = []
    # wx_failed = 0
    # for df_fire in tqdm(df_by_fire, desc='Separating fires', leave=False):
    for fire_name in tqdm(fire_areas.index, desc="Separating fires", leave=False):
        # fire_name = df_fire.iloc[0]['fire_name']
        df_fire = df_fires[df_fires["fire_name"] == fire_name]
        # NOTE: lat/lon are for centroid of group, not individual geometry
        pt_centroid = df_fire.dissolve().centroid.iloc[0]
        dists = df_wx.distance(pt_centroid)
        # figure out startup indices yesterday
        df_wx_actual = df_wx[dists == min(dists)]
        ffmc_old, dmc_old, dc_old = df_wx_actual.iloc[0][["ffmc", "dmc", "dc"]]
        dir_fire = make_run_fire(
            dir_out, df_fire, run_start, ffmc_old, dmc_old, dc_old, max_days
        )
        # wx_failed += check_failure(dir_fire, do_prep_fire(dir_fire), stop_on_any_failure)
        dirs_fire.append(dir_fire)
    # small limit due to amount of disk access
    # num_threads = int(min(len(df_fires), multiprocessing.cpu_count() / 4))
    # dirs_ready = tqdm_pool.pmap(do_prep_fire, dirs_fire, desc="Gathering weather")
    # for i in range(len(dirs_fire)):
    #     result = dirs_ready[i]
    #     dir_fire = dirs_fire[i]
    #     wx_failed += check_failure(dir_fire, result, stop_on_any_failure)
    # if 0 < wx_failed:
    #     logging.warning("%d fires could not get weather")
    # # if stop_on_any_failure and 0 < wx_failed:
    # #     logging.fatal("Stopping becase %d fires could not find weather", wx_failed)
    # #     raise RuntimeError("Could not prepare weather for all fires")
    # # HACK: weird mess to ensure thread has proper objects to call function
    # for_what = list(zip(dirs_ready, [dir_current] * len(dirs_ready)))
    # sim_results = tqdm_pool.pmap(do_run_fire, for_what, desc="Running simulations")
    # running into API 180 requests/min limit
    verbose = logging.DEBUG >= logging.getLogger().level
    for_what = list(zip(dirs_fire,
                        [dir_current] * len(dirs_fire),
                        [verbose] * len(dirs_fire)))
    sim_results = tqdm_pool.pmap(
        do_prep_and_run_fire, for_what, desc="Running simulations"
    )
    dates_out = []
    results = {}
    sim_time = 0
    sim_times = []
    NUM_TRIES = 5
    for i in range(len(sim_results)):
        result = sim_results[i]
        # HACK: should be in the same order as dirs_fire
        dir_fire = dirs_fire[i]
        if isinstance(result, Exception):
            logging.warning(f"Exception running {dir_fire} was {result}")
        tries = NUM_TRIES
        # try again if failed
        while (
            isinstance(result, Exception) or result.get("failed", True)
        ) and tries > 0:
            logging.warning("Retrying running %s", dir_fire)
            result = do_run_fire([dir_fire, dir_current, verbose])
            tries -= 1
        if isinstance(result, Exception) or result.get("failed", True):
            logging.warning("Could not run fire %s", dir_fire)
        else:
            fire_name = result["fire_name"]
            results[fire_name] = result
            if result["sim_finished"]:
                sim_time += result["sim_time"]
                sim_times.append(result["sim_time"])
                dates_out = dates_out + [x for x in result["dates_out"]]
    logging.info("Done")
    t1 = timeit.default_timer()
    totaltime = t1 - t0
    logging.info("Took %ds to run fires", totaltime)
    logging.info("Successful simulations used %ds", sim_time)
    logging.info(
        "Shortest simulation took %ds, longest took %ds", min(sim_times), max(sim_times)
    )
    logging.getLogger().removeHandler(log_run)
    return dir_out, dir_current, results, dates_out, totaltime


# # FIX: need to update to work with new directory structure and return values
# def merge_outputs(dir_out):
#     for fire_name in list_dirs(dir_out))]:
#         dir_fire = os.path.join(dir_out, fire_name)
#         print(dir_fire)
#         dir_out, log_name, dates_out = tbd.run_fire_from_folder(dir_fire)
#     merge_dirs(dir_current)


def merge_latest(dir_root):
    dir_latest = list_dirs(dir_root)[-1]
    return merge_dirs(os.path.join(dir_root, dir_latest))


if __name__ == "__main__":
    logging.info("Called with args %s", str(sys.argv))
    max_days = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_NUM_DAYS
    dir_fires = sys.argv[2] if len(sys.argv) > 2 else None
    dir_out, dir_current, results, dates_out, totaltime = run_all_fires(
        dir_fires, max_days
    )
    # simtimes, totaltime, dates = run_all_fires()
    n = len(results)
    if n > 0:
        logging.info(
            "Total of {} fires took {}s - average time is {}s".format(
                n, totaltime, totaltime / n
            )
        )
        merge_dirs(dir_current)
        publish.publish_folder(dir_current)
        import publish_azure
        publish_azure.upload_dir(dir_current)
    # dir_root = "/appl/data/output/current_m3"
