from shared import download
import certifi
import ssl
import os
import sys
sys.path.append('../util')
import common
from common import unzip


## So HTTPS transfers work properly
ssl._create_default_https_context = ssl._create_unverified_context

DATA_DIR = os.path.realpath('/FireGUARD/data')
EXTRACTED_DIR = os.path.join(DATA_DIR, 'extracted')
DOWNLOAD_DIR = os.path.join(DATA_DIR, 'download')
canada = r'http://www12.statcan.gc.ca/census-recensement/2011/geo/bound-limit/files-fichiers/lcsd000a19a_e.zip'
fbp = r'https://cwfis.cfs.nrcan.gc.ca/downloads/fuels/development/Canadian_Forest_FBP_Fuel_Types/Canadian_Forest_FBP_Fuel_Types_v20191114.zip'
nhd = r'https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/National/HighResolution/GDB/NHD_H_National_GDB.zip'

def get(url, name):
    print('Downloading {}'.format(url))
    file = download(url, DOWNLOAD_DIR)
    dir_out = os.path.join(EXTRACTED_DIR, name)
    if not os.path.exists(dir_out):
        print('Extracting {}'.format(name))
        unzip(file, dir_out)

if __name__ == '__main__':
    if not os.path.exists(EXTRACTED_DIR):
        os.makedirs(EXTRACTED_DIR)
    get(canada, r'canada')
    get(fbp, r'fbp')
    get(nhd, r'nhd')
