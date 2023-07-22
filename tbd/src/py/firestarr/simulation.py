import datetime
import json
import os
import shutil
import timeit

import datasources.spotwx
import geopandas as gpd
from gis import (
    CRS_COMPARISON,
    CRS_SIMINPUT,
    CRS_WGS84,
    area_ha,
    save_geojson,
    save_shp,
    to_gdf,
)
import model_data
import NG_FWI
import numpy as np
import pandas as pd
import pytz
import tqdm_pool
from common import (
    BOUNDS,
    CONCURRENT_SIMS,
    DEFAULT_FILE_LOG_LEVEL,
    DIR_OUTPUT,
    DIR_SIMS,
    FMT_DATE,
    FMT_TIME,
    MAX_NUM_DAYS,
    WANT_DATES,
    ParseError,
    dump_json,
    ensure_dir,
    list_dirs,
    logging,
)
from datasources.cwfis import SourceFireActive, SourceFwiCwfis
from datasources.datatypes import SourceFire
from fires import get_fires_folder, group_fires
from log import add_log_file
from publish import publish_all
from tqdm import tqdm

import tbd
from tbd import FILE_SIM


def make_run_fire(
    dir_out,
    df_fire,
    lat,
    lon,
    run_start,
    date_startup,
    ffmc_old,
    dmc_old,
    dc_old,
    max_days=None,
):
    if 1 != len(df_fire):
        raise RuntimeError("Expected exactly one fire_name run_fire()")
    fire_name = df_fire["fire_name"].iloc[0]
    df_fire = df_fire.reset_index()
    dir_fire = ensure_dir(os.path.join(dir_out, fire_name))
    logging.debug("Saving %s to %s", fire_name, dir_fire)
    file_fire = save_geojson(df_fire, os.path.join(dir_fire, fire_name))
    data = {
        # UTC time
        "job_date": run_start.strftime(FMT_DATE),
        "job_time": run_start.strftime(FMT_TIME),
        "date_startup": date_startup.isoformat(),
        "ffmc_old": ffmc_old,
        "dmc_old": dmc_old,
        "dc_old": dc_old,
        # HACK: FIX: need to actually figure this out
        "apcp_prev": 0,
        "lat": lat,
        "lon": lon,
        "perim": os.path.basename(file_fire),
        "dir_out": os.path.join(dir_fire, "firestarr"),
        "fire_name": fire_name,
        "max_days": max_days,
    }
    dump_json(data, os.path.join(dir_fire, FILE_SIM))
    return dir_fire


def do_prep_fire(dir_fire, duration=None):
    # load and update the configuration with more data
    try:
        with open(os.path.join(dir_fire, FILE_SIM)) as f:
            data = json.load(f)
    except json.JSONDecodeError as ex:
        logging.error(f"Can't read config for {dir_fire}")
        logging.error(ex)
        return ex
    lat = data["lat"]
    lon = data["lon"]
    # HACK: do this anyway for now, even though not needed if we have wx already
    # need for offset and wx
    import timezonefinder

    tf = timezonefinder.TimezoneFinder()
    tzone = tf.timezone_at(lng=lon, lat=lat)
    timezone = pytz.timezone(tzone)
    if "utcoffset_hours" not in data.keys():
        # UTC time
        # HACK: America/Inuvik is giving an offset of 0 when applied directly,
        # but says -6 otherwise
        run_start = datetime.datetime.strptime(
            f"{data['job_date']}{data['job_time']}", "%Y%m%d%H%M"
        )
        utcoffset = timezone.utcoffset(run_start)
        utcoffset_hours = utcoffset.total_seconds() / 60 / 60
        data["utcoffset_hours"] = utcoffset_hours
        # shouldn't be any way this already has a timezone if other key not present
        date_startup = (
            pd.to_datetime(data["date_startup"]).tz_localize(timezone).tz_convert("UTC")
        )
        data["date_startup"] = date_startup.isoformat()
    if "wx" not in data.keys():
        ffmc_old = data["ffmc_old"]
        dmc_old = data["dmc_old"]
        dc_old = data["dc_old"]
        try:
            src_spotwx = datasources.spotwx.SourceGEPS()
            df_wx_spotwx = src_spotwx.get_wx_model(lat, lon)
        except KeyboardInterrupt as ex:
            raise ex
        except Exception as ex:
            # logging.fatal("Could not get weather for %s", dir_fire)
            # logging.fatal(ex)
            return ex
        df_wx_filled = model_data.wx_interpolate(df_wx_spotwx)
        # gdf_geom = df_wx_filled[["lat", "lon", "geometry"]].drop_duplicates()
        # HACK: some kind of issue with NG_FWI - maybe gdf?
        df_wx_fire = (
            df_wx_filled.drop(["geometry"], axis=1)
            .rename(
                columns={
                    "lon": "long",
                    "datetime": "TIMESTAMP",
                    "precip": "PREC",
                }
            )
            .loc[:]
        )
        # HACK: just do the math for now, but don't apply a timezone
        df_wx_fire.loc[:, "TIMESTAMP"] = df_wx_fire["TIMESTAMP"] + utcoffset
        df_wx_fire.columns = [s.upper() for s in df_wx_fire.columns]
        df_wx_fire.loc[:, "YR"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].year, axis=1
        )
        df_wx_fire.loc[:, "MON"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].month, axis=1
        )
        df_wx_fire.loc[:, "DAY"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].day, axis=1
        )
        df_wx_fire.loc[:, "HR"] = df_wx_fire.apply(
            lambda x: x["TIMESTAMP"].hour, axis=1
        )
        # cols = df_wx_fire.columns
        # HACK: just get something for now
        have_noon = [x.date() for x in df_wx_fire[df_wx_fire["HR"] == 12]["TIMESTAMP"]]
        df_wx_fire = df_wx_fire[
            [x.date() in have_noon for x in df_wx_fire["TIMESTAMP"]]
        ]
        # NOTE: expects weather in localtime, but uses utcoffset to figure out local
        # sunrise/sunset
        try:
            df_fwi = NG_FWI.hFWI(df_wx_fire, utcoffset_hours, ffmc_old, dmc_old, dc_old)
        except Exception as ex:
            logging.error(ex)
            logging.error(dir_fire)
            raise ex
        # HACK: get rid of missing values at end of period
        df_fwi = df_fwi[~np.isnan(df_fwi["FWI"])].reset_index(drop=True)
        # COLUMN_SYNONYMS = {'WIND': 'WS', 'RAIN': 'PREC', 'YEAR': 'YR', 'HOUR': 'HR'}
        df_wx = df_fwi.rename(
            columns={
                "TIMESTAMP": "Date",
                "ID": "Scenario",
                "RAIN": "PREC",
                "WIND": "WS",
            }
        )
        df_wx = df_wx[
            [
                "Scenario",
                "Date",
                "PREC",
                "TEMP",
                "RH",
                "WS",
                "WD",
                "FFMC",
                "DMC",
                "DC",
                "ISI",
                "BUI",
                "FWI",
            ]
        ]
        file_wx = "wx.csv"
        df_wx.round(2).to_csv(
            os.path.join(dir_fire, file_wx), index=False, quoting=False
        )
        # HACK: make sure we're using the UTC date as the start day
        start_time = min(
            df_wx[df_wx["Date"].apply(lambda x: x.date()) >= run_start.date()]["Date"]
        ).tz_localize(timezone)
        # HACK: don't start right at start because the hour before is missing
        start_time += datetime.timedelta(hours=1)
        # if (6 > start_time.hour):
        #     start_time = start_time.replace(hour=6, minute=0, second=0)
        days_available = (df_wx["Date"].max() - df_wx["Date"].min()).days
        max_days = data["max_days"]
        want_dates = WANT_DATES
        if max_days is not None:
            want_dates = [x for x in want_dates if x <= max_days]
        offsets = [x for x in want_dates if x <= days_available]
        data["start_time"] = start_time.isoformat()
        data["offsets"] = offsets
        data["wx"] = file_wx
    if duration:
        data["offsets"] = [x for x in data["offsets"] if x <= duration]
    dump_json(data, os.path.join(dir_fire, FILE_SIM))
    return dir_fire


def do_run_fire(for_what):
    dir_fire, dir_output, verbose = for_what
    # HACK: in case do_prep_fire() failed
    if isinstance(dir_fire, Exception):
        return dir_fire
    try:
        with open(os.path.join(dir_fire, FILE_SIM)) as f:
            data = json.load(f)
            if data.get("sim_finished", False):
                # already ran
                t = data["sim_time"]
                if t is not None:
                    logging.debug(
                        "Previously ran and took {}s to run simulations".format(t)
                    )
                    return data
                else:
                    logging.debug("Previously ran but failed, so retrying")
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        logging.error(f"Error running {dir_fire}")
        logging.warning(ex)
        return ex
    # at this point everything should be in the sim file, and we can just run it
    try:
        result = tbd.run_fire_from_folder(dir_fire, dir_output, verbose=verbose)
        t = result["sim_time"]
        if t is not None:
            logging.debug("Took {}s to run simulations".format(t))
        return result
    except Exception as ex:
        logging.warning(ex)
        return ex
        # data['sim_time'] = None
        # data['dates_out'] = None
        # data['sim_finished'] = False
        # return data


# make this a function so we can call it during or after loop
def check_failure(dir_fire, result, stop_on_any_failure):
    if isinstance(result, Exception):
        logging.warning("Failed to get weather for %s", dir_fire)
        if isinstance(result, ParseError):
            file_content = os.path.join(dir_fire, "exception_content.out")
            with open(file_content, "w") as f_ex:
                # HACK: this is just where it ends up
                content = result.args[0][0]
                f_ex.write(str(content))
            with open(os.path.join(dir_fire, "exception_trace.out"), "w") as f_ex:
                f_ex.writelines(result.trace)
        else:
            with open(os.path.join(dir_fire, "exception.out"), "w") as f_ex:
                f_ex.write(str(result))
        if stop_on_any_failure:
            raise result
        return 1
    return 0


def do_prep_and_run_fire(for_what):
    dir_fire, dir_output, verbose, duration = for_what
    # change maximum duration if duration is lower
    dir_ready = do_prep_fire(dir_fire, duration)
    return do_run_fire((dir_ready, dir_output, verbose))


class SourceFireGroup(SourceFire):
    def __init__(self, dir_out, dir_fires) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._dir_fires = dir_fires

    def _get_fires(self):
        if self._dir_fires is None:
            # get perimeters from default service
            src_fires_active = SourceFireActive(self._dir_out)
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
        self, dir_fires=None, dir=None, max_days=None, do_publish=True
    ) -> None:
        self._max_days = max_days
        self._do_publish = do_publish
        self._dir_fires = dir_fires
        self._prefix = (
            "m3"
            if self._dir_fires is None
            else self._dir_fires.replace("\\", "/").strip("/").replace("/", "_")
        )
        self._log = None
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
        self._dir_data = ensure_dir(os.path.join(self._dir, "data"))
        self._dir_model = ensure_dir(os.path.join(self._dir, "model"))
        self._dir_sims = ensure_dir(os.path.join(self._dir, "sims"))
        self._dir_output = ensure_dir(os.path.join(DIR_OUTPUT, self._name))

    def log_start(self):
        if self._log is None:
            self._log = add_log_file(
                os.path.join(self._dir, f"log_{self._name}.log"),
                level=DEFAULT_FILE_LOG_LEVEL,
            )

    def log_end(self):
        if self._log:
            logging.removeHandler(self._log)
            self._log = None

    def run_all_fires(self):
        self.log_start()
        logging.info("Starting run for %s", self._name)
        # UTC time
        today = self._start_time.date()
        yesterday = today - datetime.timedelta(days=1)
        # proj = pyproj.CRS(crs)
        # keep a copy of the settings for reference
        shutil.copy(
            "/appl/tbd/settings.ini", os.path.join(self._dir_model, "settings.ini")
        )
        # also keep binary instead of trying to track source
        shutil.copy("/appl/tbd/tbd", os.path.join(self._dir_model, "tbd"))
        # only care about startup indices
        src_fwi = SourceFwiCwfis(self._dir_data)
        src_groups = SourceFireGroup(self._dir_data, self._dir_fires)
        df_fires = src_groups.get_fires()
        file_bounds = BOUNDS["bounds"]
        df_bounds = None
        if file_bounds:
            n_initial = len(df_fires)
            df_bounds = gpd.read_file(file_bounds).to_crs(df_fires.crs)
            save_shp(df_bounds, os.path.join(self._dir_data, "bounds"))
            # df_fires = df_fires.reset_index(drop=True).set_index(['fire_name'])
            df_fires = df_fires[
                df_fires.intersects(df_bounds.dissolve().iloc[0].geometry)
            ]
            logging.info(
                " ".join(
                    [
                        f"Using groups in boundaries defined by {file_bounds}",
                        f"filters fires from {n_initial} to {len(df_fires)}",
                    ]
                )
            )
            save_shp(df_fires, os.path.join(self._dir_data, "df_fires_groups_bounds"))
        # NOTE: if we do biggest first then shorter ones can fill in gaps as that one
        # takes the longest to run?
        # FIX: consider sorting by startup indices or overall DSR for period instead?
        df_fires = df_fires.to_crs(CRS_COMPARISON)
        df_fires["area"] = area_ha(df_fires)
        df_fires = df_fires.sort_values(["area"], ascending=False)
        # HACK: make into list to get rid of index so multi-column assignment works
        df_fires[["lat", "lon"]] = list(
            df_fires.centroid.to_crs(CRS_WGS84).apply(lambda pt: [pt.y, pt.x])
        )
        # get fire_name back into columns
        df_fires = df_fires.reset_index()

        def prep_row(row_fire):
            lat = row_fire["lat"]
            lon = row_fire["lon"]
            df_wx_actual = src_fwi.get_fwi(
                lat, lon, datetime_start=yesterday, datetime_end=today
            )
            ffmc_old, dmc_old, dc_old, date_startup = df_wx_actual.sort_values(
                ["datetime"], ascending=False
            ).iloc[0][["ffmc", "dmc", "dc", "datetime"]]
            df_fire = to_gdf(row_fire.to_frame().transpose(), df_fires.crs)
            dir_fire = make_run_fire(
                self._dir_sims,
                df_fire,
                lat,
                lon,
                self._start_time,
                date_startup,
                ffmc_old,
                dmc_old,
                dc_old,
                self._max_days,
            )
            return dir_fire

        tqdm.pandas(desc="Separating fires")
        dirs_fire = df_fires.progress_apply(prep_row, axis=1)
        logging.info(f"Getting weather for {len(dirs_fire)} fires")
        tqdm_pool.pmap(do_prep_fire, dirs_fire, desc="Gathering weather")
        # FIX: check the weather or folders here
        results, dates_out, total_time = self.run_fires_in_dir_by_priority(df_bounds)
        logging.info(
            f"Done running {len(dirs_fire)} fires with a total time of {total_time}"
        )
        self.log_end()
        return results, dates_out, total_time

    def run_fires_in_dir_by_priority(self, df_priority=None):
        self.log_start()
        if df_priority is None:
            file_bounds = BOUNDS["bounds"]
            if file_bounds:
                df_priority = gpd.read_file(file_bounds)
        if df_priority is not None:
            if "PRIORITY" in df_priority.columns:
                df_priority["PRIORITY"] = df_priority["PRIORITY"].astype(float)
                df_priority = df_priority.sort_values(["PRIORITY"])
            list_bounds = [df_priority.iloc[i : i + 1] for i in range(len(df_priority))]
            if "DURATION" in df_priority.columns:
                df_duration = df_priority.dissolve(by="DURATION")
                df_duration = df_duration.sort_values("DURATION", ascending=False)
        # run for each boundary in order
        total_time = 0
        all_results = {}
        all_dates = set([])
        i = 0
        for df_bounds in (pbar_area := tqdm(list_bounds, desc="Running by area")):
            if "ID" in df_bounds.columns:
                id_bounds = df_bounds.iloc[0]["ID"]
                pbar_area.set_description(f"Running by area: {id_bounds}")
            else:
                id_bounds = i
            changed = False
            results, dates_out, cur_time = self.run_fires_in_dir(df_bounds, df_duration)
            total_time += cur_time
            for k, v in results.items():
                changed = changed or v.get("ran", False)
                if k not in all_results:
                    all_results[k] = v
            all_dates = all_dates.union(set(dates_out))
            n = len(results)
            if self._do_publish and changed:
                logging.info(
                    "Total of {} fires took {}s - average time is {}s".format(
                        n, total_time, total_time / n
                    )
                )
                publish_all(self._dir_output, force=True)
                logging.debug(f"Done publishing results for {id_bounds}")
            i += 1
        self.log_end()
        return all_results, list(all_dates), total_time

    def run_fires_in_dir(self, df_bounds=None, df_duration=None, verbose=False):
        t0 = timeit.default_timer()
        dirs_fire = list_dirs(self._dir_sims)
        if df_bounds is not None:
            # logging.info("Clipping to bounds")
            df_fires = gpd.read_file(
                os.path.join(self._dir_data, "df_fires_groups.shp")
            )
            n_initial = len(dirs_fire)
            if len(df_fires) != n_initial:
                raise RuntimeError(
                    f"Expected {len(df_fires)} fire directories but have {n_initial}"
                )
            fire_names = set(df_fires["fire_name"])
            dir_names = set(dirs_fire)
            if len(fire_names.intersection(dir_names)) != len(fire_names):
                raise RuntimeError(
                    f"Directory and fire list don't match:\n{fire_names}\n{dir_names}"
                )
            df_bounds_crs = df_bounds.to_crs(df_fires.crs)
            df_fires = df_fires[
                df_fires.intersects(df_bounds_crs.dissolve().iloc[0].geometry)
            ]
        if df_duration is not None:
            df_duration_crs = df_duration.to_crs(df_fires.crs)
            df_fires = df_fires.sjoin(
                df_duration_crs.reset_index()[["geometry", "DURATION"]]
            )
            del df_fires["index_right"]
        else:
            df_fires["DURATION"] = MAX_NUM_DAYS
        fire_areas = df_fires.dissolve(by=["fire_name"]).area.sort_values(
            ascending=False
        )
        dirs_fire = list(fire_areas.index)
        durations = list(
            df_fires.set_index(["fire_name"]).loc[list(dirs_fire), "DURATION"]
        )
        dirs_fire = [os.path.join(self._dir_sims, x) for x in dirs_fire]
        # verbose = logging.DEBUG >= logging.level
        for_what = list(
            zip(
                dirs_fire,
                [self._dir_output] * len(dirs_fire),
                [verbose] * len(dirs_fire),
                durations,
            )
        )
        sim_results = tqdm_pool.pmap(
            do_prep_and_run_fire,
            for_what,
            max_processes=CONCURRENT_SIMS,
            desc="Running simulations",
        )
        dates_out = set([])
        results = {}
        sim_time = 0
        sim_times = []
        NUM_TRIES = 5
        for i in range(len(sim_results)):
            result = sim_results[i]
            # HACK: should be in the same order as dirs_fire
            dir_fire = dirs_fire[i]
            if isinstance(result, Exception):
                logging.warning(f"Exception running {dir_fire} was {result}")
            tries = NUM_TRIES
            # try again if failed
            while (
                isinstance(result, Exception) or (not result.get("sim_finished", False))
            ) and tries > 0:
                logging.warning("Retrying running %s", dir_fire)
                result = do_run_fire([dir_fire, self._dir_output, verbose])
                tries -= 1
            if isinstance(result, Exception) or (not result.get("sim_finished", False)):
                logging.warning("Could not run fire %s", dir_fire)
            else:
                fire_name = result["fire_name"]
                results[fire_name] = result
                if result["sim_finished"]:
                    cur_time = result["sim_time"]
                    if cur_time:
                        cur_time = int(cur_time)
                        sim_time += cur_time
                        sim_times.append(cur_time)
                    dates_out = dates_out.union(set(result.get("dates_out", [])))
        logging.info("Done")
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
        return results, list(dates_out), total_time


def resume(dir_resume=None):
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
    run = Run(dir=dir_resume)
    run.run_fires_in_dir_by_priority()
