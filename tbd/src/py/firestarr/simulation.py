import datetime
import os

import numpy as np
import pandas as pd
import pytz
from common import (
    FLAG_DEBUG,
    NUM_RETRIES,
    SECONDS_PER_HOUR,
    cffdrs,
    ensures,
    is_empty,
    logging,
    remove_timezone_utc,
    to_csv_safe,
    tqdm_util,
    tz_from_offset,
)
from datasources.datatypes import COLUMN_MODEL, COLUMN_TIME, COLUMNS_STREAM
from datasources.default import (
    SourceFwiBest,
    SourceHourlyBest,
    SourceModelAll,
    wx_interpolate,
)
from gis import read_gpd_file_safe, save_geojson
from timezonefinder import TimezoneFinder

from tbd import get_simulation_file


def save_wx_input(df_wx, file_wx):
    df_wx = df_wx.loc[:]
    # rename to match expected columns for firestarr csv
    df_wx.columns = [x.upper() for x in df_wx.columns]
    # FIX: assign model, id combinations scenario numbers
    df_wx = df_wx.rename(
        columns={
            COLUMN_TIME.upper(): "Date",
            COLUMNS_STREAM[-1].upper(): "Scenario",
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
    to_csv_safe(df_wx.round(2), file_wx, index=False, quoting=False)
    return file_wx


class Simulation(object):
    def __init__(self, dir_out, dir_sims, origin) -> None:
        self._dir_out = dir_out
        self._dir_sims = dir_sims
        self._origin = origin
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
        dir_fire = os.path.join(self._dir_sims, fire_name)
        file_sim = get_simulation_file(dir_fire)

        # want to return directory name of created file
        @ensures(
            file_sim,
            True,
            fct_process=os.path.dirname,
            mkdirs=True,
            retries=NUM_RETRIES,
        )
        def do_create(_):
            logging.debug("Saving %s to %s", fire_name, dir_fire)
            # this isn't going to work with locks but do we need to do it?
            # # remove directory if file doesn't exist
            # try_remove(dir_fire, verbose=False)
            # ensure_dir(dir_fire)
            max_days = row_fire["DURATION"]
            lat = row_fire["lat"]
            lon = row_fire["lon"]
            tf = TimezoneFinder()
            tz_original = pytz.timezone(tf.timezone_at(lng=lon, lat=lat))
            # figure out what timezone offset is for origin date
            # CHECK: what happens if we go over daylight savings time date?
            #        nothing I think? We're finding offset for LST here
            date_origin = pd.to_datetime(self._origin.today)
            utcoffset = date_origin - (
                (date_origin + tz_original.dst(date_origin))
                .tz_localize(tz_original)
                .tz_convert("UTC")
                .tz_localize(None)
            )
            utcoffset_hours = utcoffset.total_seconds() / SECONDS_PER_HOUR
            # do this instead of using utcoffset() so we know it's LST
            tz_lst = tz_from_offset(utcoffset)
            file_wx = _.replace(".geojson", "_wx.csv")
            file_wx_streams = _.replace(".geojson", "_wx_streams.geojson")
            # add so that loop can decrement before call
            date_try = self._origin.offset(1)
            # if no data yet then problem with data source so stop
            date_bad = self._origin.offset(-3)
            df_wx_actual = None
            while is_empty(df_wx_actual):
                date_try = date_try - datetime.timedelta(days=1)
                if date_try <= date_bad:
                    raise RuntimeError(f"Problem getting fwi for {fire_name}")
                df_wx_actual = self._src_fwi.get_fwi(lat, lon, date_try)
            ffmc_old, dmc_old, dc_old, date_startup = df_wx_actual.sort_values(
                [COLUMN_TIME], ascending=False
            ).iloc[0][["ffmc", "dmc", "dc", COLUMN_TIME]]
            # make sure we convert to LST if it's LDT
            time_startup = date_startup.tz_localize(tz_lst).tz_convert("UTC")
            # HACK: get hourly for date not time, so we can know when latest is
            df_wx_hourly_date = self._src_hourly.get_wx_hourly(
                lat, lon, time_startup.date()
            ).reset_index()
            df_wx_models = self._src_models.get_wx_model(lat, lon)
            # fill before selecting after hourly so that we always have the hour
            # right after the hourly
            df_wx_forecast = pd.concat(
                [wx_interpolate(g) for i, g in df_wx_models.groupby(COLUMN_MODEL)]
            )
            cur_time = None
            if not is_empty(df_wx_hourly_date):
                cur_time = max(df_wx_hourly_date[COLUMN_TIME])
                df_wx_forecast = df_wx_forecast.loc[
                    df_wx_forecast[COLUMN_TIME] > cur_time
                ]
            # splice every other member onto shorter members
            dates_by_model = (
                df_wx_forecast.groupby("model")[COLUMN_TIME]
                .max()
                .sort_values(ascending=False)
            )
            df_wx_forecast.loc[:, "id"] = df_wx_forecast["id"].apply(
                lambda x: f"{x:02d}"
            )
            df_spliced = None
            for (
                idx,
                model,
                date_end,
            ) in dates_by_model.reset_index().itertuples():
                df_model = df_wx_forecast.loc[df_wx_forecast["model"] == model]
                if df_spliced is not None:
                    df_append = df_spliced.loc[df_spliced[COLUMN_TIME] > date_end]
                    for i, g1 in df_model.groupby(COLUMNS_STREAM):
                        for j, g2 in df_append.groupby(COLUMNS_STREAM):
                            df_cur = pd.concat([g1, g2])
                            df_cur["model"] = f"{i[0]}x{j[0]}"
                            df_cur["id"] = f"{i[1]}x{j[1]}"
                            df_spliced = pd.concat([df_spliced, df_cur])
                else:
                    df_spliced = df_model
            df_streams = None
            # HACK: avoid comparing to empty df
            df_wx_hourly = df_wx_hourly_date
            if not is_empty(df_wx_hourly):
                # select just whatever's after startup indices time
                df_wx_hourly = df_wx_hourly_date.loc[
                    df_wx_hourly_date["datetime"] >= remove_timezone_utc(time_startup)
                ]
            if is_empty(df_wx_hourly):
                # if no hourly weather then start at start of streams
                df_streams = df_spliced
            else:
                # don't assume we aren't using multiple hourly observed streams
                for i, g1 in df_wx_hourly.groupby(COLUMNS_STREAM):
                    for j, g2 in df_spliced.groupby(COLUMNS_STREAM):
                        df_cur = pd.concat([g1, g2])
                        df_cur["model"] = f"{i[0]}x{j[0]}"
                        df_cur["id"] = f"{i[1]:02d}x{j[1]}"
                        df_streams = pd.concat([df_streams, df_cur])
            df_streams = df_streams.set_index(COLUMNS_STREAM)
            df_streams["Scenario"] = None
            # avoid:
            # 'PerformanceWarning: indexing past lexsort depth may impact performance'
            df_streams = df_streams.sort_index()
            df_stream_ids = df_streams.index.drop_duplicates()
            for i, idx in enumerate(df_stream_ids):
                df_streams.loc[idx, "Scenario"] = i
            # HACK: need id field for fwi call
            df_wx = df_streams.reset_index().rename(
                columns={
                    "id": "combination",
                    "Scenario": "id",
                    "lat": "lat_nearest",
                    "lon": "lon_nearest",
                }
            )
            df_wx.loc[:, "lat"] = lat
            df_wx.loc[:, "lon"] = lon
            # times need to be in LST for cffdrs
            df_wx.loc[:, COLUMN_TIME] = [
                x.tz_localize("UTC").tz_convert(tz_lst) for x in df_wx[COLUMN_TIME]
            ]
            if FLAG_DEBUG:
                # make it easier to see problems if cffdrs isn't working
                save_geojson(df_wx, file_wx_streams)
                df_wx = read_gpd_file_safe(file_wx_streams)
            df_wx_fire = df_wx.rename(columns={"lon": "long", COLUMN_TIME: "TIMESTAMP"})
            # remove timezone so it gets formatted properly
            df_wx_fire.loc[:, "TIMESTAMP"] = [
                x.tz_localize(None) for x in df_wx_fire["TIMESTAMP"]
            ]
            df_wx_fire.columns = [s.upper() for s in df_wx_fire.columns]
            df_wx_fire[["YR", "MON", "DAY", "HR"]] = list(
                tqdm_util.apply(
                    df_wx_fire["TIMESTAMP"],
                    lambda x: (x.year, x.month, x.day, x.hour),
                    desc="Splitting date into columns",
                )
            )
            df_wx_fire = df_wx_fire[
                [
                    "ID",
                    "LAT",
                    "LONG",
                    "TIMESTAMP",
                    "YR",
                    "MON",
                    "DAY",
                    "HR",
                    "TEMP",
                    "RH",
                    "WD",
                    "WS",
                    "PREC",
                ]
            ].sort_values(["ID", "LAT", "LONG", "TIMESTAMP"])
            # NOTE: expects weather in localtime, but uses utcoffset to
            # figure out local sunrise/sunset
            df_fwi = cffdrs.hFWI(
                df_wx_fire, utcoffset_hours, ffmc_old, dmc_old, dc_old, silent=True
            )
            # HACK: get rid of missing values at end of period
            df_fwi = df_fwi[~np.isnan(df_fwi["FWI"])].reset_index(drop=True)
            df_fwi = df_fwi.rename(
                columns={
                    "TIMESTAMP": COLUMN_TIME,
                    "RAIN": "PREC",
                    "WIND": "WS",
                }
            )
            df_fwi.columns = [x.lower() for x in df_fwi.columns]
            df_fwi[COLUMN_TIME] = df_fwi[COLUMN_TIME].apply(
                lambda x: x.tz_localize(tz_lst)
            )
            # CHECK: should be keeping weather starting at noon values so spread event
            # probability has something to work from
            df_wx = df_fwi.loc[:]
            days_available = (df_wx[COLUMN_TIME].max() - df_wx[COLUMN_TIME].min()).days
            max_days = min(days_available, max_days)
            # HACK: start from current time - assumes all fire perimeters are up
            #       to date as of latest weather
            # FIX: if we're running at noon then it didn't grab 1100 but it needs
            #       it for this
            # HACK: don't start right at start because the hour before is missing
            # HACK: compare origin UTC so day offsets are all the same dates
            start_time = (
                min(
                    df_wx[
                        df_wx[COLUMN_TIME]
                        >= pd.to_datetime(self._origin.today).tz_localize(tz_lst)
                    ][COLUMN_TIME]
                )
                .tz_convert("UTC")
                .tz_localize(None)
            ) + datetime.timedelta(hours=1)
            # if no hourly data then cur_time isn't set
            if cur_time is not None:
                start_time = max(cur_time, start_time)
            # CHECK: use start_time UTC to determine ... what exactly?
            # start time needs to be in local time
            start_time_lst = start_time.tz_localize("UTC").tz_convert(tz_lst)
            df_fire["date_startup"] = date_startup.isoformat()
            df_fire["ffmc_old"] = ffmc_old
            df_fire["dmc_old"] = dmc_old
            df_fire["dc_old"] = dc_old
            # HACK: FIX: need to actually figure this out
            df_fire["apcp_prev"] = 0
            df_fire["max_days"] = max_days
            df_fire["utcoffset_hours"] = utcoffset_hours
            df_fire["start_time"] = start_time_lst.isoformat()
            df_fire["wx"] = save_wx_input(df_wx, file_wx)
            save_geojson(df_fire, _)
            return _

        return do_create(file_sim)
