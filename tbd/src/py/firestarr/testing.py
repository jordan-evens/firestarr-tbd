import os

from main import make_resume
from run import *

from tbd import assign_firestarr_batch, find_running

self = make_resume(do_publish=False, do_merge=False)

is_batch = assign_firestarr_batch(self._dir_sims, force_local=True)

find_running(self._dir_sims)
invalid_paths = self.check_rasters(remove=False)


# not_ran = [x for x in f if not os.path.exists(os.path.join(x, "firestarr.log"))]
