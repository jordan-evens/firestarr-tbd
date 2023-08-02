from common import DIR_SCRIPTS, run_process


# HACK: just call script for now
def publish_folder(dir_current):
    stdout, stderr = run_process(
        ["/usr/bin/bash", "-c", "'./publish_geoserver.sh'"], DIR_SCRIPTS
    )
    return True
