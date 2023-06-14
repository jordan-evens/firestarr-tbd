import os
import re
import numpy as np
import shutil
import logging
import rasterio
from rasterio.enums import Resampling
import rasterio.features
from tqdm import tqdm
import pandas as pd
import geopandas as gpd
import shapely
import shapely.geometry

DIR_ROOT = r"/appl/data/output"
DIR_TMP_ROOT = os.path.join(DIR_ROOT, "service")
FILE_LOG = os.path.join(DIR_TMP_ROOT, "log.txt")
CREATION_OPTIONS = ["COMPRESS=LZW", "TILED=YES"]

logging.basicConfig(
    filename=FILE_LOG,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

DIR_OUT = r"/appl/publish"
PREFIX_DAY = "firestarr_day_"
FORMAT_DAY = PREFIX_DAY + "{:02d}"
REGEX_TIF = re.compile("^{}[0-9]*.tif$".format(PREFIX_DAY))
FACTORS = [2, 4, 8, 16]


def symbolize(file_in, file_out):
    # # write to .ovr instead of into raster
    # with rasterio.Env(TIFF_USE_OVR=True):
    #     # HACK: trying to get .ovr to compress
    with rasterio.Env(
        # # FIX: couldn't get it to compress .ovr, so just write to .tif
        # TIFF_USE_OVR=True,
        GDAL_PAM_ENABLED=True,
        ESRI_XML_PAM=True
        ):
        file_out_int = file_out.replace('.tif', '_int.tif')
        with rasterio.open(file_in, 'r') as src:
            profile = src.profile
            profile["profile"] = "GeoTIFF"
            profile_int = {k: v for k, v in profile.items()}
            profile_int['dtype'] = 'uint8'
            profile_int['nodata'] = 0
            # HACK: get length of generator so we can show progress
            n = 0
            for ji, window_ in src.block_windows(1):
                n += 1
            assert len(set(src.block_shapes)) == 1
            with rasterio.open(file_out, 'w', **profile) as dst:
                with rasterio.open(file_out_int, 'w', **profile_int) as dst_int:
                    for ji, window in tqdm(src.block_windows(1), total=n, desc=f"Processing {os.path.basename(file_in)}"):
                        # NOTE: should only be 1 band, but use all of them if more
                        d = src.read(window=window)
                        # we can read source once and use data twice
                        dst.write(d, window=window)
                        dst_int.write((10 * d).astype(int), window=window)
                logging.info("Building overviews")
            #     # NOTE: definitely do not want to blend everything out by using average
                dst.build_overviews(FACTORS, Resampling.nearest)
                dst.update_tags(ns='rio_overview', resampling='nearest')
    with rasterio.open(file_out_int, 'r') as src_int:
        crs = src_int.crs
        df = pd.DataFrame(rasterio.features.dataset_features(src_int, 1))
        df['geometry'] = df['geometry'].apply(shapely.geometry.shape)
        gdf = gpd.GeoDataFrame(df, geometry=df['geometry'], crs=crs)
        file_prob_shp = file_out.replace(".tif", ".shp").replace("-", "_")
        gdf['GRIDCODE'] = gdf['properties'].apply(lambda x: int(x['val']))
        gdf[['GRIDCODE', 'geometry']].to_file(file_prob_shp)
    os.remove(file_out_int)


# if "__main__" == __name__:
logging.info("Publishing files")
dir_input = "current_m3"
# dir_input = "current_home_bfdata_affes_latest"
dir_main = os.path.join(DIR_ROOT, dir_input)
run_id = os.listdir(dir_main)[-1]
##########################
# run_id = '202306131555'
#######################
dir_base = os.path.join(dir_main, run_id, "combined")
# find last date in directory
# redundant to use loop now that output structure is different, but still works
dir_date = [x for x in os.listdir(dir_base) if os.path.isdir(os.path.join(dir_base, x))][-1]
dir_in = os.path.join(dir_base, dir_date, "rasters")
logging.info("Using files in %s", dir_in)
files_tif = [f for f in os.listdir(dir_in) if REGEX_TIF.match(f)]
dir_tmp = os.path.join(DIR_TMP_ROOT, dir_date, run_id)
#############################
# dir_tmp += '_TEST'
#############################
logging.info("Staging in temporary directory %s", dir_tmp)
if not os.path.exists(dir_tmp):
    os.makedirs(dir_tmp)
for file in tqdm(files_tif, desc="Symbolizing files"):
    logging.info(f"Processing file")
    file_out = os.path.join(dir_tmp, file)
    file_in = os.path.join(dir_in, file)
    # shutil.copy(file_in, file_prob_tif)
    symbolize(file_in, file_out)
# HACK: using CopyRaster and CopyFeature fail, but this seems okay
for file in tqdm(os.listdir(dir_tmp), desc=f"Copying to output directory {DIR_OUT}"):
    shutil.copy(os.path.join(dir_tmp, file), os.path.join(DIR_OUT, file))
logging.info("Done")
