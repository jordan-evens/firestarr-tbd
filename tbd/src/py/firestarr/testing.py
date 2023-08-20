from main import make_resume
from run import *

self = make_resume(do_publish=False, do_merge=False)

invalid_paths = self.check_rasters(remove=False)
