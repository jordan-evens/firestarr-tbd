import os

from common import DIR_SCRIPTS


# HACK: just call script for now
def publish_folder(dir_current):
    os.system(f"{DIR_SCRIPTS}/publish_geoserver.sh")
    return True
