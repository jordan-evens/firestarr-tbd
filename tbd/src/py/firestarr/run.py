import datetime
import itertools
import os
import shutil
import time
import timeit

import numpy as np
import pandas as pd
import tqdm_util
from common import (
    BOUNDS,
    DEFAULT_FILE_LOG_LEVEL,
    DIR_OUTPUT,
    DIR_SIMS,
    FILE_LOCK_PUBLISH,
    FLAG_IGNORE_PERIM_OUTPUTS,
    FLAG_SAVE_PREPARED,
    MAX_NUM_DAYS,
    WANT_DATES,
    WX_MODEL,
    Origin,
    do_nothing,
    dump_json,
    ensure_dir,
    ensures,
    force_remove,
    list_dirs,
    locks_for,
    log_entry_exit,
    log_on_entry_exit,
    logging,
    read_json_safe,
    try_remove,
)
from datasources.datatypes import SourceFire
from datasources.default import SourceFireActive
from datasources.spotwx import get_model_dir, get_model_dir_uncached
from fires import get_fires_folder, group_fires
from gis import (
    CRS_COMPARISON,
    CRS_SIMINPUT,
    CRS_WGS84,
    area_ha,
    find_invalid_tiffs,
    make_gdf_from_series,
    read_gpd_file_safe,
    save_shp,
)
from log import LOGGER_NAME, add_log_file
from publish import merge_dirs, publish_all
from redundancy import call_safe, get_stack
from simulation import Simulation
from tqdm_util import apply, pmap, pmap_by_group, tqdm

import tbd
from tbd import (
    assign_firestarr_batch,
    check_running,
    copy_fire_outputs,
    finish_job,
    get_simulation_file,
    get_simulation_task,
    schedule_tasks,
)

LOGGER_FIRE_ORDER = logging.getLogger(f"{LOGGER_NAME}_order.log")


def log_order(*args, **kwargs):
    return log_entry_exit(logger=LOGGER_FIRE_ORDER, *args, **kwargs)


def log_order_msg(msg):
    return log_on_entry_exit(msg, LOGGER_FIRE_ORDER)


def log_order_firename():
    return log_order(show_args=lambda row_fire: row_fire.fire_name)


class SourceFireGroup(SourceFire):
    def __init__(self, dir_out, dir_fires, origin) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._dir_fires = dir_fires
        self._origin = origin

    def _get_fires(self):
        if self._dir_fires is None:
            # get perimeters from default service
            src_fires_active = SourceFireActive(self._dir_out, self._origin)
            df_fires_active = src_fires_active.get_fires()
            save_shp(df_fires_active, os.path.join(self._dir_out, "df_fires_active"))
            date_latest = np.max(df_fires_active["datetime"])
            # don't add in fires that don't match because they're out
            df_fires_groups = group_fires(df_fires_active)
            df_fires_groups["status"] = None
            # HACK: everything assumed to be up to date as of last observed change
            df_fires_groups["datetime"] = date_latest
            df_fires_groups["area"] = area_ha(df_fires_groups)
            df_fires = df_fires_groups
        else:
            # get perimeters from a folder
            df_fires = get_fires_folder(self._dir_fires, CRS_COMPARISON)
            save_shp(df_fires, os.path.join(self._dir_out, "df_fires_folder"))
            df_fires = df_fires.to_crs(CRS_COMPARISON)
            # HACK: can't just convert to lat/long crs and use centroids from that
            # because it causes a warning
            centroids = df_fires.centroid.to_crs(CRS_SIMINPUT)
            df_fires["lon"] = centroids.x
            df_fires["lat"] = centroids.y
            # df_fires = df_fires.to_crs(CRS)
        # filter out anything outside config bounds
        df_fires = df_fires[df_fires["lon"] >= BOUNDS["longitude"]["min"]]
        df_fires = df_fires[df_fires["lon"] <= BOUNDS["longitude"]["max"]]
        df_fires = df_fires[df_fires["lat"] >= BOUNDS["latitude"]["min"]]
        df_fires = df_fires[df_fires["lat"] <= BOUNDS["latitude"]["max"]]
        save_shp(df_fires, os.path.join(self._dir_out, "df_fires_groups"))
        return df_fires


class Run(object):
    def __init__(
        self,
        dir_fires=None,
        dir=None,
        max_days=None,
        do_publish=None,
        do_merge=None,
        crs=CRS_COMPARISON,
        verbose=False,
    ) -> None:
        self._verbose = verbose
        self._max_days = MAX_NUM_DAYS if not max_days else max_days
        self._do_publish = do_publish
        self._do_merge = do_merge
        self._dir_fires = dir_fires
        self._prefix = (
            "m3" if self._dir_fires is None else self._dir_fires.replace("\\", "/").strip("/").replace("/", "_")
        )
        FMT_RUNID = "%Y%m%d%H%M"
        self._modelrun = None
        if dir is None:
            self._start_time = datetime.datetime.now()
            self._id = self._start_time.strftime(FMT_RUNID)
            self._name = f"{self._prefix}_{self._id}"
            self._dir = ensure_dir(os.path.join(DIR_SIMS, self._name))
        else:
            self._name = os.path.basename(dir)
            if not self._name.startswith(self._prefix):
                raise RuntimeError(f"Trying to resume {dir} that didn't use fires from {self._prefix}")
            self._dir = dir
            self._id = self._name.replace(f"{self._prefix}_", "")
            self._start_time = datetime.datetime.strptime(self._id, FMT_RUNID)
        self._start_time = self._start_time.astimezone(datetime.timezone.utc)
        self._log = add_log_file(
            os.path.join(self._dir, f"log_{self._name}.log"),
            level=DEFAULT_FILE_LOG_LEVEL,
        )
        self._log_order = add_log_file(
            os.path.join(self._dir, f"log_order_{self._name}.log"),
            level=DEFAULT_FILE_LOG_LEVEL,
            logger=LOGGER_FIRE_ORDER,
        )
        self._dir_out = ensure_dir(os.path.join(self._dir, "data"))
        self._dir_model = ensure_dir(os.path.join(self._dir, "model"))
        self._dir_sims = ensure_dir(os.path.join(self._dir, "sims"))
        self._dir_output = ensure_dir(os.path.join(DIR_OUTPUT, self._name))
        self._crs = crs
        self._file_fires = os.path.join(self._dir_out, "df_fires_prioritized.shp")
        self._file_rundata = os.path.join(self._dir_out, "run.json")
        self.load_rundata()
        if not self._modelrun:
            self._modelrun = os.path.basename(get_model_dir(WX_MODEL))
        self.save_rundata()
        # UTC time
        self._origin = Origin(self._start_time)
        self._simulation = Simulation(self._dir_out, self._dir_sims, self._origin)
        self._src_fires = SourceFireGroup(self._dir_out, self._dir_fires, self._origin)
        self._is_batch = assign_firestarr_batch(self._dir_sims)

    def load_rundata(self):
        self._modelrun = None
        self._published_clean = False
        if os.path.isfile(self._file_rundata):
            try:
                # FIX: reorganize this or use a dictionary for other values?
                rundata = read_json_safe(self._file_rundata)
                self._modelrun = rundata.get("modelrun", None)
                self._published_clean = rundata.get("published_clean", False)
            except Exception as ex:
                logging.error(f"Couldn't load existing simulation file {self._file_rundata}")
                logging.error(get_stack(ex))

    def save_rundata(self):
        rundata = {
            "modelrun": self._modelrun,
            "published_clean": self._published_clean,
        }
        dump_json(rundata, self._file_rundata)

    def is_running(self):
        df_fires = self.load_fires()
        for fire_name in df_fires.index:
            dir_fire = os.path.join(self._dir_sims, fire_name)
            if check_running(dir_fire):
                return True
        return False

    def check_rasters(self, remove=False):
        all_tiffs = []
        # HACK: want some kind of progress bar, so make a list of files
        for root, dirs, files in os.walk(self._dir_output):
            for f in files:
                if f.endswith(".tif"):
                    all_tiffs.append(os.path.join(root, f))
        invalid_paths = find_invalid_tiffs(all_tiffs)
        if invalid_paths:
            logging.error(f"Found invalid paths:\n\t{invalid_paths}")
            if remove:
                force_remove(invalid_paths)
        return invalid_paths

    def check_and_publish(self, ignore_incomplete_okay=True, run_incomplete=False, no_publish=False):
        df_fires = self.load_fires()

        def get_df_fire(fire_name):
            return df_fires.reset_index().loc[df_fires.reset_index()["fire_name"] == fire_name]

        is_interim = {}
        is_changed = {}
        is_incomplete = {}
        is_complete = {}
        is_prepared = {}
        is_ignored = {}
        is_running = {}

        want_dates = WANT_DATES

        def check_copy_outputs(fire_name):
            try:
                dir_fire = os.path.join(self._dir_sims, fire_name)
                changed, interim, files_project = copy_fire_outputs(dir_fire, self._dir_output, changed=False)
                was_running = check_running(dir_fire)
                return dir_fire, changed, interim, files_project, was_running
            except KeyboardInterrupt as ex:
                raise ex
            except Exception:
                return dir_fire, None, None, None, None

        results = pmap(check_copy_outputs, df_fires.index, desc="Checking outputs")
        for r in tqdm(results, desc="Categorizing results"):
            dir_fire, changed, interim, files_project, was_running = r
            file_sim = get_simulation_file(dir_fire)
            df_fire = read_gpd_file_safe(file_sim) if os.path.isfile(file_sim) else None
            if changed is not None:
                is_changed[dir_fire] = changed
                is_interim[dir_fire] = interim
                if df_fire is None:
                    is_incomplete[dir_fire] = df_fire
                if was_running:
                    is_running[dir_fire] = df_fire
                else:
                    if 1 != len(df_fire):
                        raise RuntimeError(f"Expected exactly one fire in file {file_sim}")
                    data = df_fire.iloc[0]
                    max_days = data["max_days"]
                    date_offsets = [x for x in want_dates if x <= max_days]
                    len_target = len(date_offsets)
                    if not FLAG_IGNORE_PERIM_OUTPUTS:
                        len_target += 1
                    # +1 for perimeter
                    if 0 == len(files_project):
                        is_prepared[dir_fire] = df_fire
                    elif len(files_project) != len_target:
                        if ignore_incomplete_okay:
                            logging.error(f"Ignoring incomplete fire {dir_fire}")
                            is_ignored[dir_fire] = df_fire
                        else:
                            logging.warning(f"Adding incomplete fire {dir_fire}")
                            is_incomplete[dir_fire] = df_fire
                    else:
                        is_complete[dir_fire] = df_fire
            else:
                is_ignored[dir_fire] = df_fire

        def run_fire(dir_fire):
            return self.do_run_fire(dir_fire, run_only=True, no_wait=True)

        if is_prepared and run_incomplete:
            # start but don't wait
            pmap(
                run_fire,
                is_prepared.keys(),
                max_processes=len(df_fires),
                no_limit=self._is_batch,
                desc="Running prepared fires",
            )

        def reset_and_run_fire(dir_fire):
            fire_name = os.path.basename(dir_fire)
            df_fire = get_df_fire(fire_name)
            force_remove(dir_fire)
            self._simulation.prepare(df_fire)
            return self.do_run_fire(dir_fire)

        if is_incomplete and run_incomplete:
            pmap(reset_and_run_fire, is_incomplete.keys(), desc="Fixing incomplete")
        if not no_publish:
            publish_all(self._dir_output, force=changed)
        num_done = len(is_complete)
        if is_ignored:
            logging.error(f"Ignored incomplete fires: {is_ignored}")
        if ignore_incomplete_okay:
            num_done += len(is_ignored)
        return num_done == len(df_fires)

    @log_order()
    def process(self):
        logging.info("Starting run for %s", self._name)
        self.prep_fires()
        self.prep_folders()
        # FIX: check the weather or folders here
        df_final, changed = self.run_fires_in_dir(check_missing=False)
        logging.info(
            f"Done running {len(df_final)} fires with a total simulation time" f"of {df_final['sim_time'].sum()}"
        )
        return df_final, changed

    def run_until_successful_or_outdated(self):
        def is_current():
            dir_model = get_model_dir_uncached(WX_MODEL)
            modelrun = os.path.basename(dir_model)
            return modelrun == self._modelrun

        # HACK: thread is throwing errors so just actually wait for now
        result = self.run_until_successful()
        return is_current()
        # p = None
        # try:
        #     if is_current():
        #         p = Process(target=self.run_until_successful)
        #         p.start()
        #     while is_current():
        #         # keep checking if current and stop paying attention if not
        #         time.sleep(60)
        #     return is_current()
        # finally:
        #     if p and p.is_alive():
        #         p.terminate()

    def run_until_successful(self):
        is_successful = False
        while not is_successful:
            df_final, changed = self.process()
            while True:
                is_successful = self.check_and_publish()
                if is_successful:
                    # HACK: abstract this later
                    if self._is_batch:
                        finish_job()
                    break
                was_running = False
                while self.is_running():
                    was_running = True
                    logging.info("Waiting because still running")
                    time.sleep(60)
                if not was_running:
                    # publish didn't work, but nothing is running, so retry running?
                    logging.error("Changes found when publishing, but nothing running so retry")
        self._published_clean = True
        self.save_rundata()
        logging.info("Finished simulation for {self._run_id}")

        # if this is done then shouldn't need any locks for it
        def find_locks(dir_find):
            files_lock = []
            if dir_find:
                for root, dirs, files in os.walk(dir_find):
                    for f in files:
                        if f.endswith(".lock"):
                            files_lock.append(os.path.join(root, f))
            return files_lock

        logging.info(f"Removing file locks for {self._id}")
        force_remove(
            itertools.chain.from_iterable([find_locks(d) for d in [self._dir, self._dir_fires, self._dir_output]])
        )
        return df_final

    @log_order()
    def prep_fires(self, force=False):
        @ensures(self._file_fires, True, replace=force)
        def do_create(_):
            if force and os.path.isfile(_):
                logging.info("Deleting existing fires")
                force_remove(_)
            # keep a copy of the settings for reference
            shutil.copy("/appl/tbd/settings.ini", os.path.join(self._dir_model, "settings.ini"))
            # also keep binary instead of trying to track source
            shutil.copy("/appl/tbd/tbd", os.path.join(self._dir_model, "tbd"))
            df_fires = self._src_fires.get_fires().to_crs(self._crs)
            save_shp(df_fires, os.path.join(self._dir_out, "df_fires_groups.shp"))
            df_fires["area"] = area_ha(df_fires)
            # HACK: make into list to get rid of index so multi-column assignment works
            df_fires[["lat", "lon"]] = list(
                apply(
                    df_fires.centroid.to_crs(CRS_WGS84),
                    lambda pt: [pt.y, pt.x],
                    desc="Finding centroids",
                )
            )
            df_prioritized = self.prioritize(df_fires)
            save_shp(df_prioritized, _)
            return _

        return do_create(self._file_fires)

    def load_fires(self):
        if not os.path.isfile(self._file_fires):
            raise RuntimeError(f"Expected fires to be in file {self._file_fires}")
        return read_gpd_file_safe(self._file_fires).set_index(["fire_name"])

    @log_order()
    def prep_folders(self, remove_existing=False, remove_invalid=False):
        df_fires = self.load_fires()
        if remove_existing:
            # throw out folders and start over from df_fires
            force_remove(self._dir_sims)
        else:
            if not self.find_unprepared(df_fires, remove_directory=remove_invalid):
                return

        # @log_order_firename()
        def do_fire(row_fire):
            fire_name = row_fire.fire_name
            # just want a nice error message if this fails
            try:
                df_fire = make_gdf_from_series(row_fire, self._crs)
                return self._simulation.prepare(df_fire)
            except KeyboardInterrupt as ex:
                raise ex
            except Exception as ex:
                logging.error(f"Error processing fire {fire_name}")
                logging.error(get_stack(ex))
                raise ex

        list_rows = list(zip(*list(df_fires.reset_index().iterrows())))[1]
        logging.info(f"Setting up simulation inputs for {len(df_fires)} groups")
        # for row_fire in tqdm(list_rows):
        #     do_fire(row_fire)
        files_sim = pmap(
            do_fire,
            list_rows,
            desc="Preparing groups",
        )
        logging.info(f"Have {len(files_sim)} groups prepared")
        if FLAG_SAVE_PREPARED:
            try:
                df_fires_prepared = pd.concat([read_gpd_file_safe(get_simulation_file(f)) for f in files_sim])
                for col in ["datetime", "date_startup", "start_time"]:
                    df_fires_prepared.loc[:, col] = df_fires_prepared[col].astype(str)
                df_fires_prepared = df_fires_prepared.rename(
                    columns={"date_startup": "startday", "utcoffset_hours": "utcoffset"}
                )
                save_shp(
                    df_fires_prepared,
                    os.path.join(self._dir_out, "df_fires_prepared.shp"),
                )
            except Exception as ex:
                logging.debug("Couldn't save prepared fires")
                logging.debug(get_stack(ex))

    @log_order(show_args=False)
    def prioritize(self, df_fires, df_bounds=None):
        df = df_fires.loc[:]
        if df_bounds is None:
            file_bounds = BOUNDS["bounds"]
            if file_bounds:
                df_bounds = read_gpd_file_safe(file_bounds).to_crs(df.crs)
        df[["ID", "PRIORITY", "DURATION"]] = "", 0, self._max_days
        if df_bounds is not None:
            df_join = df[["geometry"]].sjoin(df_bounds)
            # only keep fires that are in bounds
            df = df.loc[np.unique(df_join.index)]
            if "PRIORITY" in df_join.columns:
                df_priority = df_join.sort_values(["PRIORITY"]).groupby("fire_name").first()
                df["ID"] = df_priority.loc[df.index, "ID"]
                df["PRIORITY"] = df_priority.loc[df.index, "PRIORITY"]
            if "DURATION" in df_bounds.columns:
                df["DURATION"] = (
                    df_join.sort_values(["DURATION"], ascending=False).groupby("fire_name").first()["DURATION"]
                )
        df["DURATION"] = np.min(list(zip([self._max_days] * len(df), df["DURATION"])), axis=1)
        df = df.sort_values(["PRIORITY", "ID", "DURATION", "area"])
        return df

    @log_order(show_args=["dir_fire"])
    def do_run_fire(self, dir_fire, prepare_only=False, run_only=False, no_wait=False):
        try:
            # return tbd.run_fire_from_folder(
            #     dir_fire, self._dir_output, verbose=self._verbose
            # )
            return call_safe(
                tbd.run_fire_from_folder,
                dir_fire,
                self._dir_output,
                prepare_only=prepare_only,
                run_only=run_only,
                no_wait=no_wait,
                verbose=self._verbose,
            )
        except KeyboardInterrupt as ex:
            raise ex
        except Exception as ex:
            logging.error(ex)
            logging.error(get_stack(ex))
            return None

    def find_unprepared(self, df_fires, remove_directory=False):
        dirs_fire = list_dirs(self._dir_sims)
        fire_names = set(df_fires.index)
        dir_names = set(dirs_fire)
        diff_extra = dir_names.difference(fire_names)
        if diff_extra:
            raise RuntimeError(f"Have directories for fires that aren't in input:\n{diff_extra}")
        expected = {f: get_simulation_file(os.path.join(self._dir_sims, f)) for f in fire_names}

        def check_file(file_sim):
            try:
                if os.path.isfile(file_sim):
                    df_fire = read_gpd_file_safe(file_sim)
                    if 1 != len(df_fire):
                        raise RuntimeError(f"Expected exactly one fire in file {file_sim}")
                    return True
            except KeyboardInterrupt as ex:
                raise ex
            except Exception:
                pass
            return False

        missing = [fire_name for fire_name, file_sim in expected.items() if not check_file(file_sim)]
        if missing:
            if remove_directory:
                logging.info(f"Need to make directories for {len(missing)} simulations")
                dirs_missing = [os.path.join(self._dir_sims, x) for x in missing]
                dirs_missing_existing = [p for p in dirs_missing if os.path.isdir(p)]
                apply(
                    dirs_missing_existing,
                    try_remove,
                    desc="Removing invalid fire directories",
                )
            else:
                logging.info(f"Need to fix geojson for {len(missing)} simulations")
                for fire_name, file_sim in expected.items():
                    try_remove(file_sim)
        return missing

    def check_do_publish(self):
        if self._do_publish is None:
            # don't publish if out of date
            return self._modelrun == get_model_dir_uncached(WX_MODEL)
        return self._do_publish

    def check_do_merge(self):
        # just for consintency with how self._do_publish works
        return self._do_merge is not False or self.check_do_publish()

    def run_fires_in_dir(self, check_missing=True):
        t0 = timeit.default_timer()
        df_fires = self.load_fires()
        if check_missing:
            if self.find_unprepared(df_fires):
                self.prep_folders()
        # HACK: order by PRIORITY so it doesn't make it alphabetical by ID
        dirs_sim = {
            id[1]: [os.path.join(self._dir_sims, x) for x in g.index] for id, g in df_fires.groupby(["PRIORITY", "ID"])
        }
        # run for each boundary in order
        changed = False
        any_change = False
        results = {}
        sim_time = 0
        sim_times = []
        # # FIX: this is just failing and delaying things over and over right now
        # NUM_TRIES = 5

        @log_order()
        def check_publish(g, sim_results):
            nonlocal changed
            nonlocal any_change
            nonlocal sim_time
            nonlocal sim_times
            nonlocal results
            with locks_for(FILE_LOCK_PUBLISH):
                for i in range(len(sim_results)):
                    result = sim_results[i]
                    # should be in the same order as input
                    dir_fire = dirs_sim[g][i]
                    if isinstance(result, Exception):
                        logging.warning(f"Exception running {dir_fire} was {result}")
                    if result is None or isinstance(result, Exception) or (not np.all(result.get("sim_time", False))):
                        logging.warning("Could not run fire %s", dir_fire)
                    else:
                        if 1 != len(result):
                            raise RuntimeError("Expected exactly one result for %s" % dir_fire)
                        row_result = result.iloc[0]
                        fire_name = row_result["fire_name"]
                        if fire_name not in results:
                            results[fire_name] = row_result
                            changed = changed or row_result.get("changed", False)
                            cur_time = row_result["sim_time"]
                            if cur_time:
                                cur_time = int(cur_time)
                                sim_time += cur_time
                                sim_times.append(cur_time)
                # keep track of if anything was ever chaned
                any_change = any_change or changed
                # check if out of date before publishing
                if changed:
                    if self.check_do_publish():
                        n = len(sim_times)
                        logging.info(
                            "Total of {} fires took {}s - average time is {}s".format(n, sim_time, sim_time / n)
                        )
                        publish_all(self._dir_output, force=changed)
                        logging.debug(f"Done publishing results for {g}")
                        # no longer changed because we just published
                    elif self.check_do_merge():
                        merge_dirs(self._dir_output)
                        logging.debug(f"Done merging directories for {g}")
                    # just updated so not changed anymore
                    changed = False

        # # use callback if at least merging
        # callback_publish = check_publish if self.check_do_merge() else do_nothing

        def prepare_fire(dir_fire):
            # print(dir_fire)
            if check_running(dir_fire):
                # already running, so prepared but no outputs
                return dir_fire
            if os.path.isfile(os.path.join(dir_fire, "sim.sh")):
                return dir_fire
            return self.do_run_fire(dir_fire, prepare_only=True)

        # schedule everything first
        pmap_by_group(
            prepare_fire,
            dirs_sim,
            desc="Preparing simulations",
        )

        def run_fire(dir_fire):
            return self.do_run_fire(dir_fire, run_only=True, no_wait=self._is_batch)

        if self._is_batch:
            dirs_fire = [os.path.join(self._dir_sims, x) for x in itertools.chain.from_iterable(dirs_sim.values())]
            # make one list of tasks and submit it
            tasks_existed = apply(
                dirs_fire,
                get_simulation_task,
                desc="Creating simulation taks",
            )
            tasks_new = [x[0] for x in tasks_existed if not x[1]]
            schedule_tasks(tasks_new)
            pmap_by_group(
                run_fire,
                dirs_sim,
                desc="Running simulations via azurebatch",
                callback_group=check_publish,
            )
        else:
            done = False
            while not done:
                try:
                    pmap_by_group(
                        run_fire,
                        dirs_sim,
                        desc="Running simulations",
                        callback_group=check_publish,
                    )
                    done = True
                except BrokenPipeError:
                    pass
        force_remove(FILE_LOCK_PUBLISH)
        # return all_results, list(all_dates), total_time
        t1 = timeit.default_timer()
        total_time = t1 - t0
        logging.info("Took %ds to run fires", total_time)
        logging.info("Successful simulations used %ds", sim_time)
        if sim_times:
            logging.info(
                "Shortest simulation took %ds, longest took %ds",
                min(sim_times),
                max(sim_times),
            )
        df_final = pd.concat([make_gdf_from_series(r, self._crs) for r in results.values()])
        try:
            save_shp(df_final, os.path.join(self._dir_out, "df_fires_final.shp"))
        except Exception as ex:
            logging.error("Couldn't save final fires")
            logging.error(get_stack(ex))
        return df_final, any_change


def make_resume(dir_resume=None, do_publish=False, do_merge=False, *args, **kwargs):
    # resume last run
    if dir_resume is None:
        dirs = [
            x for x in list_dirs(DIR_SIMS) if os.path.exists(os.path.join(DIR_SIMS, x, "data", "df_fires_groups.shp"))
        ]
        if not dirs:
            raise RuntimeError("No valid runs to resume")
        dir_resume = dirs[-1]
    dir_resume = os.path.join(DIR_SIMS, dir_resume)
    kwargs["dir"] = dir_resume
    kwargs["do_publish"] = do_publish
    kwargs["do_merge"] = do_merge
    return Run(*args, **kwargs)
