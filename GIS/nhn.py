from shared import download
import certifi
import ssl
import os
import sys
sys.path.append('../util')
import common
from common import unzip
import urllib
import zipfile
import time

## So HTTPS transfers work properly
ssl._create_default_https_context = ssl._create_unverified_context
DATA_DIR = os.path.realpath('/FireGUARD/data')
EXTRACTED_DIR = os.path.join(DATA_DIR, 'extracted')
DOWNLOAD_DIR = os.path.join(DATA_DIR, 'download')
INTERMEDIATE_DIR = os.path.join(DATA_DIR, 'intermediate')

nhn_index = r'https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/index/NHN_INDEX_WORKUNIT_LIMIT_2.zip'


from osgeo import ogr
import os, sys

def clean_shp(shp, dest, field_name_target=['DEFINITION']):
    print(shp)
    inDriver = ogr.GetDriverByName("ESRI Shapefile")
    inDataSource = inDriver.Open(shp, 0)
    inLayer = inDataSource.GetLayer()
    # Create the output LayerS
    outShapefile = os.path.join(dest, os.path.basename(shp))
    outDriver = ogr.GetDriverByName("ESRI Shapefile")
    # Remove output shapefile if it already exists
    if os.path.exists(outShapefile):
        outDriver.DeleteDataSource(outShapefile)
    # Create the output shapefile
    outDataSource = outDriver.CreateDataSource(outShapefile)
    out_lyr_name = os.path.splitext(os.path.split(outShapefile)[1])[0]
    outLayer = outDataSource.CreateLayer(out_lyr_name, geom_type=ogr.wkbMultiPolygon)
    # Add input Layer Fields to the output Layer if it is the one we want
    inLayerDefn = inLayer.GetLayerDefn()
    for i in range(0, inLayerDefn.GetFieldCount()):
        fieldDefn = inLayerDefn.GetFieldDefn(i)
        fieldName = fieldDefn.GetName()
        if fieldName not in field_name_target:
            continue
        outLayer.CreateField(fieldDefn)
    # Get the output Layer's Feature Definition
    outLayerDefn = outLayer.GetLayerDefn()
    # Add features to the ouput Layer
    for inFeature in inLayer:
        # Create output Feature
        outFeature = ogr.Feature(outLayerDefn)
        # Add field values from input Layer
        for i in range(0, outLayerDefn.GetFieldCount()):
            fieldDefn = outLayerDefn.GetFieldDefn(i)
            fieldName = fieldDefn.GetName()
            if fieldName not in field_name_target:
                continue
            outFeature.SetField(outLayerDefn.GetFieldDefn(i).GetNameRef(),
                inFeature.GetField(i))
        # Set geometry as centroid
        geom = inFeature.GetGeometryRef()
        if geom is not None:
            outFeature.SetGeometry(geom.Clone())
            # Add new feature to output Layer
            outLayer.CreateFeature(outFeature)
        outFeature = None
    # Save and close DataSources
    inDataSource = None
    outDataSource = None


def get(url, name, match):
    print('Downloading {}'.format(url))
    # if not os.path.exists(os.path.join(DOWNLOAD_DIR, os.path.basename(url))):
    file = download(url, DOWNLOAD_DIR)
    print('Extracting {}'.format(name))
    unzip(file, os.path.join(EXTRACTED_DIR, name), match)

if __name__ == '__main__':
    if not os.path.exists(EXTRACTED_DIR):
        os.makedirs(EXTRACTED_DIR)
    get(nhn_index, r'nhn_index', None)

INDEX_FILE = os.path.join(EXTRACTED_DIR, 'nhn_index/NHN_INDEX_22_INDEX_WORKUNIT_LIMIT_2.shp')

EXT_DIR = os.path.join(EXTRACTED_DIR, 'nhn')
FIX_DIR = os.path.join(INTERMEDIATE_DIR, 'nhn')

if not os.path.exists(FIX_DIR):
    os.makedirs(FIX_DIR)

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
    if f.GetGeometryRef().Intersects(bounds):
        file = f.GetField('DATASETNAM')
        matches.append(file)

bad_files = []
MASK = r'https://ftp.maps.canada.ca/pub/nrcan_rncan/vector/geobase_nhn_rhn/shp_en/{:02d}/nhn_rhn_{}_shp_en.zip'
for m in matches:
    url = MASK.format(int(m[:2]), m.lower())
    try:
        get(url, 'nhn', '_WATERBODY_2')
    except urllib.error.HTTPError:
        time.sleep(30)
        get(url, 'nhn', '_WATERBODY_2')
    except zipfile.BadZipFile:
        file = os.path.join(DOWNLOAD_DIR, os.path.basename(url))
        print("Unable to extract {}".format(url))
        os.remove(file)
        try:
            get(url, 'nhn', '_WATERBODY_2')
        except zipfile.BadZipFile:
            os.remove(file)
            url = url.replace('shp_en', 'shp_fr')
            try:
                get(url, 'nhn', '_REGIONHYDRO_2')
            except zipfile.BadZipFile:
                bad_files.append(file)

if len(bad_files) > 0:
    print("BAD FILES:")
    print(bad_files)
    sys.exit(-1)

# some files might be french, but we should have everything and it should only include waterbody data

# french and english both have a DEFINITION column so delete everything except that
shps = [os.path.join(EXT_DIR, x) for x in sorted(os.listdir(EXT_DIR)) if x.endswith('.shp')]

for shp in shps:
    clean_shp(shp, FIX_DIR)
