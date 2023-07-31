from common import DIR_SCRIPTS, run_process


# HACK: just call script for now
def publish_folder(dir_current):
    stdout, stderr = run_process(f"{DIR_SCRIPTS}/publish_geoserver.sh")
    return True
