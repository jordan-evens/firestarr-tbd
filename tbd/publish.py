import sys

sys.path.append("../util")
from log import *

import os
import re
import numpy as np
import shutil
import rasterio
from rasterio.enums import Resampling
import rasterio.features
from tqdm import tqdm
import pandas as pd
import geopandas as gpd
import shapely
import shapely.geometry

import server

from osgeo_utils import gdal_calc

DIR_ROOT = r"/appl/data/output"
DIR_TMP_ROOT = os.path.join(DIR_ROOT, "service")
FILE_LOG = os.path.join(DIR_TMP_ROOT, "log.txt")
CREATION_OPTIONS = ["COMPRESS=LZW", "TILED=YES"]

# logging.basicConfig(
#     filename=FILE_LOG,
#     level=logging.INFO,
#     format="%(asctime)s - %(levelname)s - %(message)s",
# )

DIR_OUT = r"/appl/publish"
FACTORS = [2, 4, 8, 16]


def symbolize(file_in, file_out, empty=False, with_shp=False):
    file_prob_shp = file_out.replace(".tif", ".shp").replace("-", "_")
    if not with_shp and os.path.exists(file_out):
        logging.debug("Already have %s", file_out)
    if os.path.exists(file_prob_shp):
        logging.debug("Already have %s", file_prob_shp)
        return
    # FIX: figure out if symbolizing right in the map service makes sense or not
    # # write to .ovr instead of into raster
    # with rasterio.Env(TIFF_USE_OVR=True):
    #     # HACK: trying to get .ovr to compress
    file_out_int = file_out.replace(".tif", "_int.tif")
    with rasterio.Env(
        # # FIX: couldn't get it to compress .ovr, so just write to .tif
        # TIFF_USE_OVR=True,
        GDAL_PAM_ENABLED=True,
        ESRI_XML_PAM=True,
    ):
        with rasterio.open(file_in, "r") as src:
            profile = src.profile
            profile["profile"] = "GeoTIFF"
            profile_int = {k: v for k, v in profile.items()}
            profile_int["dtype"] = "uint8"
            profile_int["nodata"] = 0
            with rasterio.open(file_out, "w", **profile) as dst:
                if with_shp:
                    dst_int = rasterio.open(file_out_int, "w", **profile_int)
                if not empty:
                    # HACK: get length of generator so we can show progress
                    n = 0
                    for ji, window_ in src.block_windows(1):
                        n += 1
                    assert len(set(src.block_shapes)) == 1
                    for ji, window in tqdm(
                        src.block_windows(1),
                        total=n,
                        desc=f"Processing {os.path.basename(file_in)}",
                    ):
                        # NOTE: should only be 1 band, but use all of them if more
                        d = src.read(window=window)
                        # we can read source once and use data twice
                        dst.write(d, window=window)
                        if with_shp:
                            dst_int.write((10 * d).astype(int), window=window)
                    if with_shp:
                        dst_int.close()
                else:
                    "Creating empty outputs"
                # logging.info("Building overviews")
                # NOTE: definitely do not want to blend everything out by using average
                dst.build_overviews(FACTORS, Resampling.nearest)
                dst.update_tags(ns="rio_overview", resampling="nearest")
    if with_shp:
        with rasterio.open(file_out_int, "r") as src_int:
            crs = src_int.crs
            df = pd.DataFrame(rasterio.features.dataset_features(src_int, 1))
            if 0 == len(df):
                df["geometry"] = []
                df["GRIDCODE"] = []
            else:
                df["geometry"] = df["geometry"].apply(shapely.geometry.shape)
                df["GRIDCODE"] = df["properties"].apply(lambda x: int(x["val"]))
            schema = {"geometry": "Polygon", "properties": {"GRIDCODE": "int"}}
            gdf = gpd.GeoDataFrame(df, geometry=df["geometry"], crs=crs)
            # specify more to try avoiding UserWarning if empty dataframe
            gdf[["GRIDCODE", "geometry"]].to_file(
                file_prob_shp, schema=schema, driver="ESRI Shapefile", crs=crs
            )
        os.remove(file_out_int)


def publish_folder(dir_runid, with_shp=False):
    if not os.path.isdir(DIR_OUT):
        logging.warning(
            "Publish directory %s doesn't exist, so not publishing %s",
            DIR_OUT,
            dir_runid,
        )
    if not server.FOLDER:
        logging.warning(
            "No server defined, so not publishing %s",
            dir_runid,
        )
    logging.info("Publishing %s", dir_runid)
    run_id = os.path.basename(dir_runid)
    dir_base = os.path.join(dir_runid, "combined")
    # find last date in directory
    # redundant to use loop now that output structure is different,
    # but still works
    dir_date = [
        x for x in os.listdir(dir_base) if os.path.isdir(os.path.join(dir_base, x))
    ][-1]
    dir_in = os.path.join(dir_base, dir_date)
    REGEX_TIF_SIMPLE = re.compile("^firestarr_day_[0-9]*.tif$")
    PREFIX_DAY = f"firestarr_{run_id}_day_"
    FORMAT_DAY = PREFIX_DAY + "{:02d}"
    REGEX_TIF = re.compile("^{}([0-9]*)_([0-9]*).tif$".format(PREFIX_DAY))
    logging.info("Using files in %s", dir_in)
    files_tif_orig = [f for f in os.listdir(dir_in) if REGEX_TIF.match(f)]
    f = files_tif_orig[-1]
    # need to lop off the date from the end for this service
    i = f.rindex("_")
    n = int(f[(f[:i].rindex("_") + 1) : i])
    dir_tmp = os.path.join(DIR_TMP_ROOT, dir_date, run_id)
    files_tif = [
        f"{f[:f.rindex('_')]}.tif".replace(f"_{run_id}", "") for f in files_tif_orig
    ]
    #############################
    # dir_tmp += '_TEST'
    #############################
    # logging.info("Staging in temporary directory %s", dir_tmp)
    # if not os.path.exists(dir_tmp):
    #     os.makedirs(dir_tmp)
    # files_tif_processed = [f for f in os.listdir(dir_tmp) if REGEX_TIF.match(f)]
    files_tif_service = [f for f in os.listdir(DIR_OUT) if REGEX_TIF_SIMPLE.match(f)]
    # if ((len(files_tif_service) > len(files_tif))
    #         or (files_tif[:len(files_tif_service)] != files_tif_service)):
    #     logging.fatal(f"Files to be published do not match files that service is using:\n%s != %s",
    #                   str(files_tif), str(files_tif_service))
    #     raise RuntimeError("Files to be published do not match files that service is using")
    if files_tif_service != files_tif:
        logging.warning(
            f"Files to be published do not match files that service is using:\n%s != %s",
            str(files_tif),
            str(files_tif_service),
        )
    files_missing = [x for x in files_tif_service if x not in files_tif]
    if 0 < len(files_missing):
        logging.warning("Will create empty files for %s", str(files_missing))
    file_template = os.path.join(dir_in, files_tif_orig[0])
    files_tif_simple = files_tif
    for f in files_missing:
        logging.warning(f"Creating empty file for {f}")
        args = [
            "gdal_calc.py",
            "--calc",
            "0",
            "-A",
            f"{file_template}",
            "--NoDataValue",
            "0",
            "--overwrite",
            "--outfile",
            f"{os.path.join(DIR_OUT, f)}",
            "--quiet",
            "--creation-option",
            "COMPRESS=LZW",
            "--creation-option",
            "NUM_THREADS=ALL_CPUS",
            "--creation-option",
            "TILED=YES",
            # "--format",
            # "COG",
            "--creation-option",
            "NBITS=16",
            # "--creation-option",
            # "ADD_ALPHA=NO",
            "--creation-option",
            "SPARSE_OK=TRUE",
            # "--creation-option",
            # "PREDICTOR=YES",
        ]
        logging.info(" ".join(args))
        gdal_calc.main(args)
    files_tif = [f for f in os.listdir(dir_in) if REGEX_TIF.match(f)]
    # for file in tqdm(files_tif + files_missing, desc="Symbolizing files"):
    #     file_out = os.path.join(dir_tmp, file)
    #     file_in = os.path.join(
    #         dir_in, (file_template if file in files_missing else file)
    #     )
    #     # shutil.copy(file_in, file_prob_tif)
    #     symbolize(file_in, file_out, empty=(file in files_missing), with_shp=with_shp)
    # # HACK: copying seems to take a while, so try to do this without stopping before copy
    # # logging.info("Stopping services")
    # # server.stopServices()
    # # HACK: using CopyRaster and CopyFeature fail, but this seems okay
    # for file in tqdm(
    #     os.listdir(dir_tmp), desc=f"Copying to output directory {DIR_OUT}"
    # ):
    #     shutil.copy(os.path.join(dir_tmp, file), os.path.join(DIR_OUT, file))
    for i in tqdm(range(len(files_tif)), desc=f"Copying to output directory {DIR_OUT}"):
        shutil.copy(
            os.path.join(dir_in, files_tif[i]),
            os.path.join(DIR_OUT, files_tif_simple[i]),
        )
    # update metadata
    summary = f"FireSTARR outputs for {n} day run {run_id}"
    updates = {
        "summary": summary,
        "description": summary,
    }
    server.updateMetadata(updates, remove_keys=["extent", "error"])
    # restart whether or not update metadata worked
    logging.info("Restarting services")
    server.restartServices()
    logging.info("Done")


def publish_latest(dir_input="current_m3", with_shp=False):
    logging.info(f"Publishing latest files for {dir_input}")
    # dir_input = "current_home_bfdata_affes_latest"
    dir_main = os.path.join(DIR_ROOT, dir_input)
    run_id = [
        x
        for x in os.listdir(dir_main)
        if os.path.isdir(os.path.join(dir_main, x, "combined"))
    ][-1]
    ##########################
    # run_id = '202306131555'
    #######################
    dir_runid = os.path.join(dir_main, run_id)
    publish_folder(dir_runid, with_shp)


if "__main__" == __name__:
    publish_latest()
