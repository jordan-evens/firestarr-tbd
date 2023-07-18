from __future__ import print_function

import os
import re
import arcpy

# make sure all the layers point to the same file name pattern as the template

PREFIX_DAY = "firestarr_day_"
FORMAT_DAY = PREFIX_DAY + "{:02d}"
REGEX_TIF = re.compile("^{}[0-9]*.tif$".format(PREFIX_DAY))
TEMPLATE_GROUP = FORMAT_DAY.format(1)

# redundant to use loop now that output structure is different, but still works

mxd = arcpy.mapping.MapDocument("CURRENT")
lyrs = arcpy.mapping.ListLayers(mxd)
groups = [lyr.name for lyr in lyrs if lyr.isGroupLayer]
lyr_groups_template = arcpy.mapping.ListLayers(mxd, TEMPLATE_GROUP)
if 0 == len(lyr_groups_template):
    raise RuntimeError(
        "Need '{}' as a template for other days".format(TEMPLATE_GROUP)
    )
if 1 < len(lyr_groups_template):
    raise RuntimeError(
        "Multiple layers exist matching template group name '{}'".format(
            TEMPLATE_GROUP
        )
    )
lyr_template = lyr_groups_template[0]
# use directory and day for everything else
lyr_base = [x for x in arcpy.mapping.ListLayers(lyr_template)
            if not x.isGroupLayer][0]
print("Assigning data sources based on value of {}: \"{}\"".format(
    lyr_base.name, lyr_base.dataSource))
dir_base = os.path.dirname(lyr_base.dataSource)
lyr_groups = arcpy.mapping.ListLayers(mxd, PREFIX_DAY + "*")
# do all the groups, even the template, in case we just changed the first
# item in the template layer
for group in lyr_groups:
    print(group.name)
    day = int(group.name[(group.name.rindex('_') + 1):])
    for lyr in arcpy.mapping.ListLayers(group):
        if not lyr.isGroupLayer:
            src_orig = lyr.dataSource
            # shapefiles don't want extension
            suffix = src_orig[src_orig.rindex('.'):].replace(".shp", "")
            src_new = FORMAT_DAY.format(day) + suffix
            lyr.replaceDataSource(dir_base, "NONE", src_new)
