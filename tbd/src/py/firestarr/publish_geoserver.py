import os

# HACK: just call script for now
def publish_folder(dir_current):
    os.system("/appl/tbd/scripts/publish_geoserver.sh")
    return True
