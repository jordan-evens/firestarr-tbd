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
dirs_sim = {id[1]: [os.path.join(self._dir_sims, x) for x in g.index] for id, g in df_fires.groupby(["PRIORITY", "ID"])}
# run for each boundary in order
changed = False
any_change = False
results = {}
sim_time = 0
sim_times = []
# # FIX: this is just failing and delaying things over and over right now
# NUM_TRIES = 5
file_lock_publish = os.path.join(self._dir_output, "publish")


dirs_fire = [os.path.join(self._dir_sims, x) for x in itertools.chain.from_iterable(dirs_sim.values())]
dir_fire = dirs_fire[0]

dir_fire
dir_output = self._dir_output
prepare_only = True
run_only = False
verbose = self._verbose


# from tbd import *

# def nolog(*args, **kwargs):
#     pass

# def dolog(msg, *args, **kwargs):
#     logging.info(f"{dir_fire}: {msg}", *args, **kwargs)

# if prepare_only and run_only:
#     raise RuntimeError("Can't prepare_only and run_only at the same time")
# log_info = dolog if verbose else nolog

# was_running = check_running(dir_fire)
# if was_running:
#     log_info(f"Already running {dir_fire} - waiting for it to finish")
# while check_running(dir_fire):
#     time.sleep(10)
# if was_running:
#     log_info(f"Continuing after {dir_fire} finished running")

# file_sim = get_simulation_file(dir_fire)
# # need directory for lock
# ensure_dir(os.path.dirname(file_sim))
# # lock before reading so if sim is running it will update file before lock ends


# df_fire = gdf_from_file(file_sim) if os.path.isfile(file_sim) else None
# if df_fire is None:
#     raise RuntimeError(f"Couldn't get fire data from {file_sim}")
# if 1 != len(df_fire):
#     raise RuntimeError(f"Expected exactly one fire in file {file_sim}")
# data = df_fire.iloc[0]
# # check if completely done
# # if data.get("postprocessed", False):
# #     df_fire["changed"] = False
# #     return df_fire
# changed = False
# fire_name = data["fire_name"]
# # file_log = file_sim.replace(".geojson", ".log")
# file_log = os.path.join(dir_fire, "firestarr.log")
# df_fire["log_file"] = file_log
# sim_time = data.get("sim_time", None)
# if not sim_time:
#     # try parsing log for simulation time
#     sim_time = None
#     if os.path.exists(file_log):
#         # if log says it ran then don't run it
#         # HACK: just use tail instead of looping or seeking ourselves
#         stdout, stderr = run_process(["tail", "-1", file_log], "/appl/tbd")
#         if stdout:
#             line = stdout.strip().split("\n")[-1]
#             g = re.match(".*Total simulation time was (.*) seconds", line)
#             if g and g.groups():
#                 sim_time = int(g.groups()[0])
# want_dates = WANT_DATES
# max_days = data["max_days"]
# date_offsets = [x for x in want_dates if x <= max_days]
# # HACK: rerun if not enough outputs
# outputs = listdir_sorted(dir_fire)
# probs = [
#     x for x in outputs if x.endswith("tif") and x.startswith("probability")
# ]
# if not sim_time or len(probs) != len(date_offsets):
#     if not run_only:
#         lat = float(data["lat"])
#         lon = float(data["lon"])
#         start_time = pd.to_datetime(data["start_time"])
#         log_info(f"Scenario start time is: {start_time}")
#         if "Point" != data.geometry.geom_type:
#             year = start_time.year
#             reference = find_best_raster(lon, year)
#             raster = os.path.join(dir_fire, "{}.tif".format(fire_name))
#             with locks_for(raster):
#                 # FIX: if we never use points then the sims don't guarantee
#                 # running from non-fuel for the points like normally
#                 perim = Rasterize(file_sim, raster, reference)
#         else:
#             # think this should be fine for using individual points
#             save_point_file(lat, lon, dir_fire, fire_name)
#             perim = None
#         log_info("Startup coordinates are {}, {}".format(lat, lon))
#         hour = start_time.hour
#         minute = start_time.minute
#         tz = (
#             start_time.tz.utcoffset(start_time).total_seconds()
#             / SECONDS_PER_HOUR
#         )
#         # HACK: I think there might be issues with forecasts being at
#         #           the half hour?
#         if math.floor(tz) != tz:
#             logging.warning("Rounding down to deal with partial hour timezone")
#             tz = math.floor(tz)
#         tz = int(tz)
#         log_info("Timezone offset is {}".format(tz))
#         start_date = start_time.date()
#         cmd = os.path.join(DIR_TBD, "tbd")
#         wx_file = os.path.join(dir_fire, data["wx"])
#         # want format like a list with no spaces
#         fmt_offsets = "[" + ",".join([str(x) for x in date_offsets]) + "]"

#         def strip_dir(path):
#             p = os.path.abspath(path)
#             d = os.path.abspath(dir_fire)
#             if p.startswith(d):
#                 p = p[len(d) + 1 :]
#             if 0 == len(p):
#                 p = "."
#             return p

#         # FIX: --log doesn't work right now
#         args = " ".join(
#             [
#                 f'"{strip_dir(dir_fire)}" {start_date} {lat} {lon}',
#                 f"{hour:02d}:{minute:02d}",
#                 NO_INTENSITY,
#                 f"--ffmc {data['ffmc_old']}",
#                 f"--dmc {data['dmc_old']}",
#                 f"--dc {data['dc_old']}",
#                 f"--apcp_prev {data['apcp_prev']}",
#                 "-v",
#                 f"--output_date_offsets {fmt_offsets}",
#                 f"--wx {strip_dir(wx_file)}",
#                 # f"--log {strip_dir(file_log)}",
#             ]
#         )
#         if perim is not None:
#             args = args + f" --perim {strip_dir(perim)}"
#         args = args.replace("\\", "/")
#         file_sh = os.path.join(dir_fire, "sim.sh")

#         def mk_sim_sh(*a, **k):
#             with open(file_sh, "w") as f_out:
#                 f_out.writelines(["#!/bin/bash\n", f"{cmd} {args}\n"])

#         call_safe(mk_sim_sh)
#         # NOTE: needs to be octal base
#         os.chmod(file_sh, 0o775)


def prepare_fire(dir_fire):
    if check_running(dir_fire):
        # already running, so prepared but no outputs
        return dir_fire
    if os.path.isfile(os.path.join(dir_fire, "sim.sh")):
        return dir_fire
    return self.do_run_fire(dir_fire, prepare_only=True)


# for dir_fire in dirs_fire:
#     print(dir_fire)
#     prepare_fire(dir_fire)


# schedule everything first
dirs_prepared = tqdm_util.pmap_by_group(
    prepare_fire,
    dirs_sim,
    desc="Preparing simulations",
)


def run_fire(dir_fire):
    return self.do_run_fire(dir_fire, run_only=True)


# tqdm_util.keep_trying(
#     run_fire,
#     dirs_fire,
#     max_processes=len(df_fires) if self._is_batch else CONCURRENT_SIMS,
#     no_limit=self._is_batch,
#     desc="Running simulations",
# )

tqdm_util.pmap_by_group(
    run_fire,
    dirs_sim,
    max_processes=len(df_fires) if self._is_batch else CONCURRENT_SIMS,
    no_limit=self._is_batch,
    desc="Running simulations",
)
