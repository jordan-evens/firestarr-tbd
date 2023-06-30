# Import the library
from geo.Geoserver import Geoserver
USERNAME="jevans"
PASSWORD="Firestarr is better than PFAS, right?!"
SERVER="http://app-geoserver-wips-cwfis-prod.azurewebsites.net/geoserver"
WORKSPACE="firestarr"
LAYER="firestarr_day"
STYLE="'../data/tmp/probability.sld'"
# /rest
# WORKSPACE=${SERVER}/workspaces/firestarr
# STORE=$WORKSPACE/coveragestores/${LAYER}

DIR="../data/output/current_m3/202306291635/combined/20230629"
PREFIX="firestarr_202306290124_day_"
SRC=f"{PREFIX}01_20230629"
tif=f"{DIR}/{SRC}.tif"
# SRC2="${PREFIX}02_20230630"
# SRC3="${PREFIX}03_20230701"
# SRC7="${PREFIX}07_20230705"
# SRC14="${PREFIX}14_20230712"

# Initialize the library
geo = Geoserver(SERVER, username=USERNAME, password=PASSWORD)

# For creating workspace
# geo.create_workspace(workspace=WORKSPACE)

# For uploading raster data to the geoserver
# geo.create_coveragestore(layer_name='layer1', path=r'path\to\raster\file.tif', workspace='demo')
geo.upload_style(path=STYLE, workspace=WORKSPACE)
lyrs = []
n = 0
import re
for tif in os.listdir(DIR):
    run_id, for_what, for_day = re.match("firestarr_(\d{12})_(.*)_(\d{8}).tif", tif).groups()
    g = re.match('day_(\d{2})', for_what)
    if g:
        n = max(n, int(g.groups()[0]))
    lyr = f"firestarr_{for_what}"
    lyrs.append(lyr)
    geo.create_coveragestore(layer_name=lyr,
                            path=os.path.join(DIR, tif),
                            workspace=WORKSPACE)
    geo.publish_style(layer_name=lyr,
                      style_name=os.path.splitext(os.path.basename(STYLE))[0],
                      workspace=WORKSPACE)

# summary = f"FireSTARR outputs for {n} day run {run_id}"
# metadata = {
#     "summary": summary,
#     "description": summary,
# }

geo.create_layer_group(name="firestarr",
                       title="FireSTARR",
                       abstract_text=f"FireSTARR run for {run_id}",
                       layers=lyrs,
                       workspace=WORKSPACE)
# geo.create_coveragestyle(raster_path=tif,
#                          style_name='probability',
#                          workspace=WORKSPACE)
# geo.publish_style(layer_name=LAYER, style_name='probability', workspace=WORKSPACE)


# # For creating postGIS connection and publish postGIS table
# geo.create_featurestore(store_name='geo_data', workspace='demo', db='postgres', host='localhost', pg_user='postgres',
#                         pg_password='admin')
# geo.publish_featurestore(workspace='demo', store_name='geo_data', pg_table='geodata_table_name')

# For uploading SLD file and connect it with layer
geo.upload_style(path=r'path\to\sld\file.sld', workspace='demo')
geo.publish_style(layer_name='geoserver_layer_name', style_name='sld_file_name', workspace='demo')

# For creating the style file for raster data dynamically and connect it with layer
geo.create_coveragestyle(raster_path=r'path\to\raster\file.tiff', style_name='style_1', workspace='demo',
                         color_ramp='RdYiGn')
geo.publish_style(layer_name='geoserver_layer_name', style_name='raster_file_name', workspace='demo')

# delete workspace
geo.delete_workspace(workspace='demo')

# delete layer
geo.delete_layer(layer_name='agri_final_proj', workspace='demo')

# delete style file
geo.delete_style(style_name='kamal2', workspace='demo')
