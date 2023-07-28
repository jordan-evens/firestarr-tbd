import datetime
import os

import NG_FWI
import numpy as np
import pandas as pd
import pytz
from common import (
    FMT_DATE_YMD,
    FMT_TIME,
    Origin,
    ensure_dir,
    logging,
    remove_on_exception,
    tqdm_util,
    try_remove,
)
from datasources.datatypes import COLUMN_MODEL, COLUMN_STREAM, COLUMN_TIME
from datasources.default import (
    SourceFwiBest,
    SourceHourlyBest,
    SourceModelAll,
    wx_interpolate,
)
from gis import save_geojson
from timezonefinder import TimezoneFinder

from tbd import get_simulation_file


class Simulation(object):
    def __init__(self, dir_out) -> None:
        self._dir_out = dir_out
        self._src_fwi = SourceFwiBest(self._dir_out)
        self._src_models = SourceModelAll(self._dir_out)
        self._src_hourly = SourceHourlyBest(self._dir_out)

    def prepare(self, df_fire):
        if len(df_fire) > 1:
            raise RuntimeError("Expected exactly one row")
        if "fire_name" not in df_fire.columns:
            raise RuntimeError("Expected fire_name to be in columns")
        row_fire = df_fire.iloc[0]
        fire_name = row_fire["fire_name"]
        dir_out = row_fire["dir_sims"]
        dir_fire = os.path.join(dir_out, fire_name)
        file_sim = get_simulation_file(dir_fire)
        if os.path.isfile(file_sim):
            return dir_fire
        # remove directory if file doesn't exist
        try_remove(dir_fire, verbose=False)
        dir_fire = ensure_dir(dir_fire)
        with remove_on_exception(dir_fire):
            lat = row_fire["lat"]
            lon = row_fire["lon"]
            run_start = pd.to_datetime(row_fire["start_time"])
            max_days = row_fire["DURATION"]
            origin = Origin(run_start)
            # add so that loop can decrement before call
            date_try = origin.offset(1)
            df_wx_actual = None
            while df_wx_actual is None or 0 == len(df_wx_actual):
                date_try = date_try - datetime.timedelta(days=1)
                df_wx_actual = self._src_fwi.get_fwi(lat, lon, date_try)
            ffmc_old, dmc_old, dc_old, date_startup = df_wx_actual.sort_values(
                ["datetime"], ascending=False
            ).iloc[0][["ffmc", "dmc", "dc", "datetime"]]
            tf = TimezoneFinder()
            tzone = tf.timezone_at(lng=lon, lat=lat)
            timezone = pytz.timezone(tzone)
            wx_start = (
                pd.to_datetime(date_startup) + datetime.timedelta(hours=12)
            ).tz_localize(timezone)
            utcoffset = wx_start.utcoffset()
            utcoffset_hours = utcoffset.total_seconds() / 60 / 60

            def calc_model(df_wx_model):
                df_wx_filled = wx_interpolate(df_wx_model)
                df_wx_fire = df_wx_filled.rename(
                    columns={"lon": "long", COLUMN_TIME: "TIMESTAMP"}
                )
                # HACK: do the math for local time, but don't apply a timezone
                df_wx_fire["TIMESTAMP"] = df_wx_fire["TIMESTAMP"] + utcoffset
                df_wx_fire.columns = [s.upper() for s in df_wx_fire.columns]
                df_wx_fire[["YR", "MON", "DAY", "HR"]] = list(
                    tqdm_util.apply(
                        df_wx_fire["TIMESTAMP"],
                        lambda x: (x.year, x.month, x.day, x.hour),
                        desc="Splitting date into columns",
                    )
                )
                # HACK: just get something for now
                have_noon = [
                    x.date() for x in df_wx_fire[df_wx_fire["HR"] == 12]["TIMESTAMP"]
                ]
                df_wx_fire = df_wx_fire[
                    [x.date() in have_noon for x in df_wx_fire["TIMESTAMP"]]
                ]
                # NOTE: expects weather in localtime, but uses utcoffset to
                # figure out local sunrise/sunset
                df_fwi = NG_FWI.hFWI(
                    df_wx_fire, utcoffset_hours, ffmc_old, dmc_old, dc_old
                )
                # HACK: get rid of missing values at end of period
                df_fwi = df_fwi[~np.isnan(df_fwi["FWI"])].reset_index(drop=True)
                df_wx = df_fwi.rename(
                    columns={
                        "TIMESTAMP": COLUMN_TIME,
                        "RAIN": "PREC",
                        "WIND": "WS",
                    }
                )
                df_wx.columns = [x.lower() for x in df_wx.columns]
                return df_wx

            df_wx_models = self._src_models.get_wx_model(lat, lon)
            df_wx = pd.concat(
                [calc_model(g) for i, g in df_wx_models.groupby(COLUMN_MODEL)]
            )
            df_wx[COLUMN_TIME] = df_wx[COLUMN_TIME].apply(
                lambda x: x.tz_localize(timezone)
            )
            utcoffsets = np.unique(df_wx[COLUMN_TIME].apply(lambda x: x.utcoffset()))
            if 1 != len(utcoffsets):
                raise RuntimeError(
                    f"Expected weather with single UTC offset but got {utcoffsets}"
                )
            utcoffset_hours = utcoffsets[0].astype("timedelta64[h]").astype(np.float32)
            days_available = (df_wx[COLUMN_TIME].max() - df_wx[COLUMN_TIME].min()).days
            max_days = min(days_available, max_days)
            # HACK: make sure we're using the UTC date as the start day
            start_time = min(
                df_wx[
                    tqdm_util.apply(
                        df_wx[COLUMN_TIME], lambda x: x.date(), desc="Finding date"
                    )
                    >= origin.today
                ][COLUMN_TIME]
            )
            # HACK: don't start right at start because the hour before is missing
            start_time += datetime.timedelta(hours=1)
            logging.debug("Saving %s to %s", fire_name, dir_fire)
            file_fire = os.path.join(dir_fire, fire_name)
            df_fire["job_date"] = run_start.strftime(FMT_DATE_YMD)
            df_fire["job_time"] = run_start.strftime(FMT_TIME)
            df_fire["date_startup"] = (date_startup.isoformat(),)
            df_fire["ffmc_old"] = ffmc_old
            df_fire["dmc_old"] = dmc_old
            df_fire["dc_old"] = dc_old
            # HACK: FIX: need to actually figure this out
            df_fire["apcp_prev"] = 0
            df_fire["perim"] = os.path.basename(file_fire)
            df_fire["max_days"] = max_days
            df_fire["utcoffset_hours"] = utcoffset_hours
            df_fire["date_startup"] = date_startup.isoformat()
            df_fire["start_time"] = start_time.isoformat()
            file_wx = file_sim.replace(".geojson", "_wx.csv")
            df_fire["wx"] = os.path.basename(file_wx)
            # rename to match expected columns for firestarr csv
            df_wx.columns = [x.upper() for x in df_wx.columns]
            df_wx = df_wx.rename(
                columns={
                    COLUMN_TIME.upper(): "Date",
                    COLUMN_STREAM.upper(): "Scenario",
                }
            )[
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
            # remove timezone so it outputs in expected format
            df_wx["Date"] = df_wx["Date"].apply(lambda x: x.tz_localize(None))
            df_wx.round(2).to_csv(file_wx, index=False, quoting=False)
            save_geojson(df_fire, file_sim)
            return dir_fire
