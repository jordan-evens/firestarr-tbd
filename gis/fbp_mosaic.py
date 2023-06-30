from __future__ import print_function

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
sys.path.append('../util')
import common

import sys
sys.path.append(os.path.dirname(sys.executable))
import gdal_merge as gm


DATA_DIR = os.path.realpath('../data')
GIS = os.path.join(DATA_DIR, 'gis')
TIF_DIR = os.path.join(GIS, 'fbp')
INPUT = os.path.join(GIS, 'input')
GIS_FBP = os.path.join(INPUT, 'fbp')

if __name__ == '__main__':
    for cellsize in [30, 100]:
        in_dir = f'{DATA_DIR}/extracted/fbp{cellsize:03d}m'
        fbp = f'{GIS_FBP}/fbp{cellsize:03d}m.tif'
        if not os.path.exists(fbp):
            if not os.path.exists(GIS_FBP):
                os.makedirs(GIS_FBP)
            print('Mosaicing...')
            src_files_to_mosaic = [x for x in glob.glob(os.path.join(in_dir, '*.tif'))]
            gm.main(['', '-co', 'COMPRESS=DEFLATE', '-co', 'BIGTIFF=YES',
                     '-o', fbp] + src_files_to_mosaic)
