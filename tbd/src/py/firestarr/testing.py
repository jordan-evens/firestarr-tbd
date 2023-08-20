import itertools
import os
import timeit

import tqdm_util
from common import CONCURRENT_SIMS
from main import make_resume

from tbd import assign_firestarr_batch, check_running

self = make_resume(do_publish=False, do_merge=False)

self.prep_folders()

# is_batch = assign_firestarr_batch(self._dir_sims)
# # is_batch = assign_firestarr_batch(self._dir_sims, force_local=True)

# find_running(self._dir_sims)
# invalid_paths = self.check_rasters(remove=False)


# # not_ran = [x for x in f if not os.path.exists(os.path.join(x, "firestarr.log"))]


check_missing = True
t0 = timeit.default_timer()
df_fires = self.load_fires()
if check_missing:
    if self.find_unprepared(df_fires):
        self.prep_folders()
is_batch = assign_firestarr_batch(self._dir_sims)
# HACK: order by PRIORITY so it doesn't make it alphabetical by ID
dirs_sim = {
    id[1]: [os.path.join(self._dir_sims, x) for x in g.index]
    for id, g in df_fires.groupby(["PRIORITY", "ID"])
}
# run for each boundary in order
changed = False
any_change = False
results = {}
sim_time = 0
sim_times = []
# # FIX: this is just failing and delaying things over and over right now
# NUM_TRIES = 5
file_lock_publish = os.path.join(self._dir_output, "publish")


def prepare_fire(dir_fire):
    if check_running(dir_fire):
        # already running, so prepared but no outputs
        return dir_fire
    return self.do_run_fire(dir_fire, prepare_only=True)


# schedule everything first
dirs_prepared = tqdm_util.pmap_by_group(
    prepare_fire,
    dirs_sim,
    desc="Preparing simulations",
)


dirs_fire = [
    os.path.join(self._dir_sims, x)
    for x in itertools.chain.from_iterable(dirs_sim.values())
]


def run_fire(dir_fire):
    return self.do_run_fire(dir_fire, run_only=True)


tqdm_util.pmap(
    run_fire,
    dirs_fire,
    desc="Running simulations",
)

tqdm_util.pmap_by_group(
    run_fire,
    dirs_sim,
    max_processes=len(df_fires) if is_batch else CONCURRENT_SIMS,
    no_limit=is_batch,
    desc="Running simulations",
)
