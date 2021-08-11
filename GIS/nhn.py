from shared import download
from shared import unzip
import certifi
import ssl
import os
import sys
sys.path.append('../util')
import common
import urllib

## So HTTPS transfers work properly
ssl._create_default_https_context = ssl._create_unverified_context
DATA_DIR = os.path.realpath('/FireGUARD/data')
EXTRACTED_DIR = os.path.join(DATA_DIR, 'extracted')
DOWNLOAD_DIR = os.path.join(DATA_DIR, 'download')

nhn_index = r'https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/index/NHN_INDEX_WORKUNIT_LIMIT_2.zip'


def get(url, name):
    print('Downloading {}'.format(url))
    file = download(url, DOWNLOAD_DIR)
    print('Extracting {}'.format(name))
    unzip(file, os.path.join(EXTRACTED_DIR, name))

if __name__ == '__main__':
    if not os.path.exists(EXTRACTED_DIR):
        os.makedirs(EXTRACTED_DIR)
    get(nhn_index, r'nhn_index')

INDEX_FILE = '/FireGUARD/data/extracted/nhn_index/NHN_INDEX_22_INDEX_WORKUNIT_LIMIT_2.shp'

import ogr
DRIVER_SHP = ogr.GetDriverByName('ESRI Shapefile')
index = DRIVER_SHP.Open(INDEX_FILE)
indexLayer = index.GetLayer()

xLeft = float(common.CONFIG.get('FireGUARD','longitude_min'))
xRight = float(common.CONFIG.get('FireGUARD','longitude_max'))
yBottom = float(common.CONFIG.get('FireGUARD','latitude_min'))
yTop = float(common.CONFIG.get('FireGUARD','latitude_max'))

srs = ogr.osr.SpatialReference()
srs.ImportFromEPSG(4269)
ring = ogr.Geometry(ogr.wkbLinearRing)
ring.AddPoint(xLeft, yTop)
ring.AddPoint(xLeft, yBottom)
ring.AddPoint(xRight, yBottom)
ring.AddPoint(xRight, yTop)
ring.AddPoint(xLeft, yTop)
bounds = ogr.Geometry(ogr.wkbPolygon)
bounds.AddGeometry(ring)
bounds.AssignSpatialReference(srs)
coordTrans = ogr.osr.CoordinateTransformation(srs, indexLayer.GetSpatialRef())
bounds.Transform(coordTrans)

matches = []

for i in range(indexLayer.GetFeatureCount()):
    f = indexLayer.GetFeature(i)
    # print(f)
    if f.GetGeometryRef().Intersects(bounds):
        file = f.GetField('DATASETNAM')
        # print(file)
        matches.append(file)

MASK = r'https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/shp_en/{:02d}/nhn_rhn_{}_shp_en.zip'
for m in matches:
    url = MASK.format(int(m[:2]), m.lower())
    try:
        get(url, 'nhn')
    except urllib.error.HTTPError:
        sleep(30)
        get(url, 'nhn')

