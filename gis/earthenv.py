from __future__ import print_function
#~ r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_N80W180.tar.gz'
#~ r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_N80W005.tar.gz'
#~ r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_N80E000.tar.gz'
#~ r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_N80E175.tar.gz'


#~ r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_N00W180.tar.gz'
#~ r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_S05W180.tar.gz'
#~ url = r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_S55W180.tar.gz'

import os
import multiprocessing
import tarfile
import math

import rasterio
from rasterio.merge import merge
from rasterio.plot import show
import glob
import logging
import sys
import common

import osgeo_utils.gdal_merge as gm


DATA_DIR = os.path.realpath('../data')
GIS = os.path.join(DATA_DIR, 'gis')
OUT_DIR = os.path.join(DATA_DIR, 'extracted/earthenv')
TIF_DIR = os.path.join(GIS, 'earthenv')
INPUT = os.path.join(GIS, "input")
GIS_ELEVATION = os.path.join(INPUT, "elevation")
EARTHENV = os.path.join(GIS_ELEVATION, "EarthEnv.tif")
MASK = r'http://mirrors.iplantcollaborative.org/earthenv_dem_data/EarthEnv-DEM90/EarthEnv-DEM90_{}{}.tar.gz'
DOWNLOAD_DIR = os.path.join(DATA_DIR, 'download/ftp', os.path.dirname(MASK.replace('http://', '')))

def define_bounds():
    global RANGE_LATITUDE
    global RANGE_LONGITUDE
    MIN_LAT = int(common.BOUNDS['latitude']['min'] / 5) * 5
    if MIN_LAT < 0 and 0 != MIN_LAT  / 5:
        MIN_LAT -= 5
    MAX_LAT = math.ceil(common.BOUNDS['latitude']['max'] / 5) * 5
    if MAX_LAT < 85 and 0 != MAX_LAT / 5:
        MAX_LAT += 5
    RANGE_NORTH = list(map(lambda _: 'N{:02d}'.format(_),
                      [x for x in reversed([5 * x for x in list(range(17))]) if x >= MIN_LAT and x <= MAX_LAT]))
    RANGE_SOUTH = list(map(lambda _: 'S{:02d}'.format(_),
                      [x for x in [(5 * (x + 1)) for x in list(range(11))] if -x >= MIN_LAT and -x <= MAX_LAT]))
    MIN_LON = int(common.BOUNDS['longitude']['min'] / 5) * 5
    if MIN_LON < 0 and 0 != MIN_LON  / 5:
        MIN_LON -= 5
    MAX_LON = math.ceil(common.BOUNDS['longitude']['max'] / 5) * 5
    MAX_LON -= 5
    RANGE_WEST = list(map(lambda _: 'W{:03d}'.format(_),
                     [x for x in reversed([5 * (x + 1) for x in list(range(36))]) if -x >= MIN_LON and -x <= MAX_LON]))
    RANGE_EAST = list(map(lambda _: 'E{:03d}'.format(_),
                     [x for x in [5 * x for x in list(range(36))] if x >= MIN_LON and x <= MAX_LON]))
    RANGE_LATITUDE = RANGE_NORTH + RANGE_SOUTH
    RANGE_LONGITUDE = RANGE_WEST + RANGE_EAST


def to_download(url):
    save_as = os.path.join(DOWNLOAD_DIR, os.path.basename(url))
    return common.save_http(url, save_as, ignore_existing=True)

if __name__ == '__main__':
    if not os.path.exists(EARTHENV):
        pool = multiprocessing.Pool(processes=4)
        urls = []
        define_bounds()
        for lat in RANGE_LATITUDE:
            for lon in RANGE_LONGITUDE:
                urls.append(MASK.format(lat, lon))
        print('Downloading...')
        retries = 0
        while retries < 5:
            try:
                files = pool.map(to_download, urls)
                break
            except:
                print('Downloading failed')
                retries = retries + 1
        if 5 == retries:
            print('Too many retries')
            sys.exit(-1)
        if not os.path.exists(OUT_DIR):
            os.mkdir(OUT_DIR)
        print('Extracting...')
        for f in files:
            print(f)
            tar = tarfile.open(f)
            tar.extractall(OUT_DIR)
            tar.close()
        # HACK: some .bil files don't work with gdal, so convert with rasterio to start
        import rasterio
        files = glob.glob(os.path.join(OUT_DIR, '*.bil'))
        common.ensure_dir(TIF_DIR)
        for file in files:
            print(file)
            out_file = os.path.join(TIF_DIR, os.path.basename(file.replace('.bil', '.tif')))
            if not os.path.exists(out_file):
                with rasterio.open(file) as src:
                    out_meta = src.meta.copy()
                    out_meta.update({"driver": "GTiff"})
                    array = src.read(1)
                    with rasterio.open(out_file,
                                        "w", **out_meta, compress='DEFLATE',
                                        tiled=True, blockxsize=256, blockysize=256) as dest1:
                        dest1.write(array.astype(rasterio.uint16), 1)
        if not os.path.exists(GIS_ELEVATION):
            os.makedirs(GIS_ELEVATION)
        print('Mosaicing...')
        dem_fps = glob.glob(os.path.join(TIF_DIR, "EarthEnv-DEM90_*.tif"))
        src_files_to_mosaic = []
        for fp in dem_fps:
           src_files_to_mosaic.append(fp)
        gm.main(['', '-co', 'COMPRESS=DEFLATE', '-co', 'BIGTIFF=YES', '-o', EARTHENV] + src_files_to_mosaic)
