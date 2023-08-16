import datetime
import os
import shutil
import timeit

import geopandas as gpd
import numpy as np
import pandas as pd
import tqdm_util
from common import (
    BOUNDS,
    CONCURRENT_SIMS,
    DEFAULT_FILE_LOG_LEVEL,
    DIR_OUTPUT,
    DIR_SIMS,
    MAX_NUM_DAYS,
    Origin,
    do_nothing,
    ensure_dir,
    ensures,
    list_dirs,
    locks_for,
    log_entry_exit,
    log_on_entry_exit,
    logging,
    message_on_exception,
    try_remove,
)
from datasources.datatypes import SourceFire
from datasources.default import SourceFireActive
from fires import get_fires_folder, group_fires
from gis import (
    CRS_COMPARISON,
    CRS_SIMINPUT,
    CRS_WGS84,
    area_ha,
    make_gdf_from_series,
    save_shp,
)
from log import LOGGER_NAME, add_log_file
from publish import merge_dirs, publish_all
from simulation import Simulation

import tbd
from tbd import assign_firestarr_batch, get_simulation_file

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
        do_publish=True,
        do_merge=True,
        crs=CRS_COMPARISON,
        verbose=False,
    ) -> None:
        self._verbose = verbose
        self._max_days = MAX_NUM_DAYS if not max_days else max_days
        self._do_publish = do_publish
        self._do_merge = do_merge or do_publish
        self._dir_fires = dir_fires
        self._prefix = (
            "m3"
            if self._dir_fires is None
            else self._dir_fires.replace("\\", "/").strip("/").replace("/", "_")
        )
        FMT_RUNID = "%Y%m%d%H%M"
        if dir is None:
            self._start_time = datetime.datetime.now()
            self._id = self._start_time.strftime(FMT_RUNID)
            self._name = f"{self._prefix}_{self._id}"
            self._dir = ensure_dir(os.path.join(DIR_SIMS, self._name))
        else:
            self._name = os.path.basename(dir)
            if not self._name.startswith(self._prefix):
                raise RuntimeError(
                    f"Trying to resume {dir} that didn't use fires from {self._prefix}"
                )
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
        # UTC time
        self._origin = Origin(self._start_time)
        self._simulation = Simulation(self._dir_out, self._dir_sims, self._origin)
        self._src_fires = SourceFireGroup(self._dir_out, self._dir_fires, self._origin)

    @log_order()
    def process(self):
        logging.info("Starting run for %s", self._name)
        self.prep_fires()
        self.prep_folders()
        # FIX: check the weather or folders here
        df_final = self.run_fires_in_dir(check_missing=False)
        logging.info(
            f"Done running {len(df_final)} fires with a total simulation time"
            f"of {df_final['sim_time'].sum()}"
        )
        return df_final

    @log_order()
    def prep_fires(self, force=False):
        @ensures(self._file_fires, True, replace=force)
        def do_create(_):
            if force and os.path.isfile(_):
                logging.info("Deleting existing fires")
                try_remove(_)
            # keep a copy of the settings for reference
            shutil.copy(
                "/appl/tbd/settings.ini", os.path.join(self._dir_model, "settings.ini")
            )
            # also keep binary instead of trying to track source
            shutil.copy("/appl/tbd/tbd", os.path.join(self._dir_model, "tbd"))
            df_fires = self._src_fires.get_fires().to_crs(self._crs)
            save_shp(df_fires, os.path.join(self._dir_out, "df_fires_groups.shp"))
            df_fires["area"] = area_ha(df_fires)
            # HACK: make into list to get rid of index so multi-column assignment works
            df_fires[["lat", "lon"]] = list(
                tqdm_util.apply(
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
        return gpd.read_file(self._file_fires).set_index(["fire_name"])

    @log_order()
    def prep_folders(self, remove_existing=False):
        df_fires = self.load_fires()
        if remove_existing:
            # throw out folders and start over from df_fires
            try_remove(self._dir_sims)
        else:
            if not self.find_unprepared(df_fires, remove_invalid=True):
                return

        # @log_order_firename()
        def do_fire(row_fire):
            fire_name = row_fire.fire_name
            # just want a nice error message if this fails
            with message_on_exception(f"Error processing fire {fire_name}"):
                # HACK: can't pickle with @log_order
                with log_order_msg(f"do_fire({fire_name})"):
                    df_fire = make_gdf_from_series(row_fire, self._crs)
                    return self._simulation.prepare(df_fire)

        list_rows = list(zip(*list(df_fires.reset_index().iterrows())))[1]
        logging.info(f"Setting up simulation inputs for {len(df_fires)} groups")
        # for row_fire in list_rows:
        #     do_fire(row_fire)
        tqdm_util.pmap(
            do_fire,
            list_rows,
            desc="Preparing groups",
        )

    @log_order(show_args=False)
    def prioritize(self, df_fires, df_bounds=None):
        df = df_fires.loc[:]
        if df_bounds is None:
            file_bounds = BOUNDS["bounds"]
            if file_bounds:
                df_bounds = gpd.read_file(file_bounds).to_crs(df.crs)
        df[["ID", "PRIORITY", "DURATION"]] = "", 0, self._max_days
        if df_bounds is not None:
            df_join = df[["geometry"]].sjoin(df_bounds)
            # only keep fires that are in bounds
            df = df.loc[np.unique(df_join.index)]
            if "PRIORITY" in df_join.columns:
                df_priority = (
                    df_join.sort_values(["PRIORITY"]).groupby("fire_name").first()
                )
                df["ID"] = df_priority.loc[df.index, "ID"]
                df["PRIORITY"] = df_priority.loc[df.index, "PRIORITY"]
            if "DURATION" in df_bounds.columns:
                df["DURATION"] = (
                    df_join.sort_values(["DURATION"], ascending=False)
                    .groupby("fire_name")
                    .first()["DURATION"]
                )
        df["DURATION"] = np.min(
            list(zip([self._max_days] * len(df), df["DURATION"])), axis=1
        )
        df = df.sort_values(["PRIORITY", "ID", "DURATION", "area"])
        return df

    @log_order(show_args=["dir_fire"])
    def do_run_fire(self, dir_fire):
        try:
            return tbd.run_fire_from_folder(
                dir_fire, self._dir_output, verbose=self._verbose
            )
        except KeyboardInterrupt as ex:
            raise ex
        except Exception as ex:
            logging.error(ex)
            return None

    def find_unprepared(self, df_fires, remove_invalid=False):
        dirs_fire = list_dirs(self._dir_sims)
        fire_names = set(df_fires.index)
        dir_names = set(dirs_fire)
        diff_extra = dir_names.difference(fire_names)
        if diff_extra:
            raise RuntimeError(
                f"Have directories for fires that aren't in input:\n{diff_extra}"
            )
        expected = {
            f: get_simulation_file(os.path.join(self._dir_sims, f)) for f in fire_names
        }
        missing = [
            fire_name
            for fire_name, file_sim in expected.items()
            if not os.path.isfile(file_sim)
        ]
        if missing:
            logging.info(f"Need to make directories for {len(missing)} simulations")
            if remove_invalid:
                dirs_missing = [os.path.join(self._dir_sims, x) for x in missing]
                dirs_missing_existing = [p for p in dirs_missing if os.path.isdir(p)]
                tqdm_util.apply(
                    dirs_missing_existing,
                    shutil.rmtree,
                    desc="Removing invalid fire directories",
                )
        return missing

    def run_fires_in_dir(self, check_missing=True):
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
        dates_out = set([])
        results = {}
        sim_time = 0
        sim_times = []
        # FIX: this is just failing and delaying things over and over right now
        NUM_TRIES = 5
        file_lock_publish = os.path.join(self._dir_output, "publish")

        @log_order()
        def check_publish(g, sim_results):
            nonlocal changed
            nonlocal sim_time
            nonlocal sim_times
            nonlocal dates_out
            nonlocal results
            with locks_for(file_lock_publish):
                for i in range(len(sim_results)):
                    result = sim_results[i]
                    # should be in the same order as input
                    dir_fire = dirs_sim[g][i]
                    if isinstance(result, Exception):
                        logging.warning(f"Exception running {dir_fire} was {result}")
                    tries = NUM_TRIES
                    # try again if failed
                    while (
                        result is None
                        or isinstance(result, Exception)
                        or (not np.all(result.get("postprocessed", False)))
                    ) and tries > 0:
                        logging.warning("Retrying running %s", dir_fire)
                        result = self.do_run_fire(dir_fire)
                        tries -= 1
                    if (
                        result is None
                        or isinstance(result, Exception)
                        or (not np.all(result.get("sim_time", False)))
                    ):
                        logging.warning("Could not run fire %s", dir_fire)
                    elif not np.all(result.get("postprocessed", False)):
                        logging.warning(
                            "Ran fire %s, but couldn't postprocess" % dir_fire
                        )
                    else:
                        if 1 != len(result):
                            raise RuntimeError(
                                "Expected exactly one result for %s" % dir_fire
                            )
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
                            dates_out = dates_out.union(
                                set(row_result.get("dates_out", []))
                            )
                if self._do_publish and changed:
                    n = len(sim_times)
                    logging.info(
                        "Total of {} fires took {}s - average time is {}s".format(
                            n, sim_time, sim_time / n
                        )
                    )
                    publish_all(self._dir_output, force=True)
                    logging.debug(f"Done publishing results for {g}")
                else:
                    merge_dirs(self._dir_output, force=True)
                    logging.debug(f"Done merging directories for {g}")

        callback_publish = check_publish if self._do_merge else do_nothing
        tqdm_util.pmap_by_group(
            self.do_run_fire,
            dirs_sim,
            max_processes=len(df_fires) if is_batch else CONCURRENT_SIMS,
            no_limit=is_batch,
            desc="Running simulations",
            callback_group=callback_publish,
        )
        try_remove(file_lock_publish)
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
        df_final = pd.concat(
            [make_gdf_from_series(r, self._crs) for r in results.values()]
        )
        # FIX: save doesn't work with fields in there right now
        # save_geojson(df_final, self._file_fires)
        return df_final


def make_resume(dir_resume=None, *args, **kwargs):
    # resume last run
    if dir_resume is None:
        dirs = [
            x
            for x in list_dirs(DIR_SIMS)
            if os.path.exists(os.path.join(DIR_SIMS, x, "data", "df_fires_groups.shp"))
        ]
        if not dirs:
            raise RuntimeError("No valid runs to resume")
        dir_resume = dirs[-1]
    dir_resume = os.path.join(DIR_SIMS, dir_resume)
    logging.info(f"Resuming previous run in {dir_resume}")
    kwargs["dir"] = dir_resume
    return Run(*args, **kwargs)
