import datetime
from functools import cache
import os
from collections import Counter

import geopandas as gpd
from gis import CRS_COMPARISON, CRS_WGS84, KM_TO_M, area_ha, area_ha_to_radius_m
import model_data
import numpy as np
import pandas as pd
from common import (
    DEFAULT_M3_LAST_ACTIVE_IN_DAYS,
    DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS,
    DIR_SRC_PY_FIRSTARR,
    USE_CWFIS_SERVICE,
    YEAR,
    listdir_sorted,
    logging,
    pick_max,
    pick_max_by_column,
    save_http,
    to_utc,
    try_save,
)
from datasources.datatypes import SourceFeature, SourceFire, SourceFwi, make_point
from model_data import DEFAULT_STATUS_IGNORE, query_geoserver

ONE_DAY = datetime.timedelta(days=1)


class SourceFeatureM3Service(SourceFeature):
    def __init__(self, dir_out, last_active_since=datetime.date.today()) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._last_active_since = last_active_since

    @cache
    def _get_features(self):
        f_out = f"{self._dir_out}/m3_polygons.json"
        features = "lastdate,geometry"
        table_name = "public:m3_polygons"
        filter = None
        if self._last_active_since:
            filter = (
                f"lastdate >= {self._last_active_since.strftime('%Y-%m-%d')}T00:00:00Z"
            )
        f_json = query_geoserver(table_name, f_out, features=features, filter=filter)
        logging.debug(f"Reading {f_json}")
        df = gpd.read_file(f_json)
        df["datetime"] = to_utc(df["lastdate"])
        since = pd.to_datetime(self._last_active_since, utc=True)
        return df.loc[df["datetime"] >= since]


class SourceFeatureM3Download(SourceFeature):
    def __init__(self, dir_out, last_active_since=datetime.date.today()) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._last_active_since = last_active_since

    @cache
    def _get_features(self):
        def get_shp(filename):
            for ext in ["dbf", "prj", "shx", "shp"]:
                url = (
                    f"https://cwfis.cfs.nrcan.gc.ca/downloads/hotspots/{filename}.{ext}"
                )
                f_out = os.path.join(self._dir_out, os.path.basename(url))
                f = try_save(lambda _: save_http(_, f_out), url)
            gdf = gpd.read_file(f)
            return gdf

        df = get_shp("perimeters")
        df["datetime"] = to_utc(df["LASTDATE"])
        since = pd.to_datetime(self._last_active_since, utc=True)
        return df.loc[df["datetime"] >= since]


class SourceFeatureM3(SourceFeature):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        if DEFAULT_M3_LAST_ACTIVE_IN_DAYS:
            last_active_since = datetime.date.today() - datetime.timedelta(
                days=DEFAULT_M3_LAST_ACTIVE_IN_DAYS
            )
        else:
            last_active_since = None
        if USE_CWFIS_SERVICE:
            self._source = SourceFeatureM3Service(dir_out, last_active_since)
        else:
            self._source = SourceFeatureM3Download(dir_out, last_active_since)

    def _get_features(self):
        return self._source.get_features()


def make_name_ciffc(df):
    def make_name(date, agency, fire):
        return f"{date.year}_{agency.upper()}_{fire}"

    return df.apply(
        lambda x: make_name(
            x["datetime"], x["field_agency_code"], x["field_agency_fire_id"]
        ),
        axis=1,
    )


class SourceFireDipService(SourceFire):
    def __init__(self, dir_out, status_ignore=DEFAULT_STATUS_IGNORE, year=YEAR) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._status_ignore = status_ignore
        self._year = year

    @cache
    def _get_fires(self):
        df, j = model_data.get_fires_dip(self._dir_out, self._status_ignore, self._year)
        df = df.rename(
            columns={
                "stage_of_control": "status",
                "firename": "field_agency_fire_id",
                "hectares": "area",
                "last_rep_date": "datetime",
                "agency": "field_agency_code",
            }
        )
        df["fire_name"] = make_name_ciffc(df)
        df = df.to_crs(CRS_WGS84)
        return df


class SourceFireCiffcService(SourceFire):
    def __init__(self, dir_out, status_ignore=DEFAULT_STATUS_IGNORE) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._status_ignore = status_ignore

    @cache
    def _get_fires(self):
        df, j = model_data.get_fires_ciffc(self._dir_out, self._status_ignore)
        df = df.rename(
            columns={
                "field_status_date": "datetime",
                "field_stage_of_control_status": "status",
                "field_fire_size": "area",
            }
        )
        df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        df["fire_name"] = make_name_ciffc(df)
        df = df.loc[df["datetime"].apply(lambda x: x.year) == YEAR]
        df = df.set_index(["fire_name"])
        dupes = [k for k, v in Counter(df.reset_index()["fire_name"]).items() if v > 1]
        df_dupes = df.loc[dupes].reset_index()
        df = df.drop(dupes)
        df_dupes.sort_values(["fire_name", "datetime", "area"], ascending=False)[
            ["fire_name", "datetime", "area", "status"]
        ]
        df_pick = (
            df_dupes.sort_values(["fire_name", "datetime", "area"], ascending=False)
            .groupby(["fire_name"])
            .first()
        )
        df_pick.crs = df_dupes.crs
        df = pd.concat([df, df_pick])
        return df


class SourceFireCiffc(SourceFire):
    def __init__(self, dir_out, status_ignore=DEFAULT_STATUS_IGNORE, year=YEAR) -> None:
        super().__init__(bounds=None)
        self._source_ciffc = SourceFireCiffcService(dir_out, status_ignore)
        self._source_dip = SourceFireDipService(dir_out, status_ignore, year)

    def _get_fires(self):
        try:
            return self._source_ciffc.get_fires()
        except KeyboardInterrupt as ex:
            raise ex
        except Exception:
            return self._source_dip.get_fires()


def get_fwi(lat, lon, df_wx, columns):
    for index in columns:
        df_wx = df_wx.loc[~df_wx[index].isna()]
    cols_float = [x for x in df_wx.columns if x not in ["datetime", "geometry"]]
    df_wx[cols_float] = df_wx[cols_float].astype(float)
    df_wx = df_wx.to_crs(CRS_COMPARISON)
    pt = make_point(lat, lon, CRS_COMPARISON)
    dists = df_wx.distance(pt)
    df_wx = df_wx.loc[dists == min(dists)]
    return df_wx


class SourceFwiCwfisDownload(SourceFwi):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out

    def _get_fwi(self, lat, lon, datetime_start=None, datetime_end=None):
        if datetime_start is None:
            datetime_start = datetime.date.today() - ONE_DAY
        if datetime_end is None:
            datetime_end = datetime.date.today()
        dates = list(pd.date_range(start=datetime_start, end=datetime_end, freq="D"))
        df_wx = None
        # do individually so @cache can hash arguments
        for date in dates:
            df_wx = pd.concat(
                [
                    df_wx,
                    model_data.get_wx_cwfis_download(
                        self._dir_out, date, ",".join(self.columns)
                    ),
                ]
            )
        df_wx["datetime"] = df_wx["datetime"] + datetime.timedelta(hours=12)
        return get_fwi(lat, lon, df_wx, self.columns)


class SourceFwiCwfisService(SourceFwi):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out

    def _get_fwi(self, lat, lon, datetime_start=None, datetime_end=None):
        if datetime_start is None:
            datetime_start = datetime.date.today() - ONE_DAY
        if datetime_end is None:
            datetime_end = datetime.date.today()
        dates = list(pd.date_range(start=datetime_start, end=datetime_end, freq="D"))
        df_wx = None
        # do individually so @cache can hash arguments
        for date in dates:
            df_wx = pd.concat(
                [
                    df_wx,
                    model_data.get_wx_cwfis(
                        self._dir_out, date, indices=",".join(self.columns)
                    ),
                ]
            )
        return get_fwi(lat, lon, df_wx, self.columns)


class SourceFwiCwfis(SourceFwi):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        if USE_CWFIS_SERVICE:
            self._source = SourceFwiCwfisService(dir_out)
        else:
            self._source = SourceFwiCwfisDownload(dir_out)

    def _get_fwi(self, lat, lon, datetime_start=None, datetime_end=None):
        return self._source.get_fwi(lat, lon, datetime_start, datetime_end)


STATUS_RANK = ["OUT", "UC", "BH", "OC", "UNK"]


def find_rank(x):
    # rank is highest if unknown value
    return STATUS_RANK.index(x) if x in STATUS_RANK else (len(STATUS_RANK) - 1)


def assign_fires(
    df_features,
    df_fires,
    days_to_keep_unmatched=DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS,
):
    # do this to make an index column
    df_features = df_features.reset_index().to_crs(CRS_COMPARISON)
    df_fires = df_fires.reset_index().to_crs(CRS_COMPARISON)
    df_join = df_features.sjoin_nearest(df_fires, how="left", max_distance=1 * KM_TO_M)
    df_join["status_rank"] = df_join["status"].apply(find_rank)
    df_unmatched = df_join[df_join["fire_name"].isna()][
        ["datetime_left", "geometry"]
    ].rename(columns={"datetime_left": "datetime"})
    # HACK: if unmatched then ignore more readily based on age
    min_active = to_utc(
        datetime.date.today() - datetime.timedelta(days=days_to_keep_unmatched)
    )
    df_unmatched = df_unmatched[df_unmatched["datetime"] >= min_active].reset_index(
        drop=True
    )
    df_join = df_join[~df_join["fire_name"].isna()]
    df_join = df_join.sort_values(
        ["index", "status_rank", "area", "fire_name"], ascending=False
    )
    # should mean only one copy of each geometry, and picked by fire with highest status
    df_first = df_join.groupby("index").first()
    # doesn't have crs after groupby
    df_first.crs = df_join.crs
    # dissolve by fire_name but use max so highest lastdate stays
    df_dissolve = df_first.dissolve(by="fire_name", aggfunc="max").reset_index()
    df_dissolve["datetime"] = pick_max(
        df_dissolve["datetime_left"], df_dissolve["datetime_right"]
    )
    df_matched = df_dissolve[["fire_name", "datetime", "status", "geometry"]]
    df_features = df_matched.reset_index(drop=True)
    df_features["area"] = area_ha(df_features)
    df_unmatched["area"] = area_ha(df_unmatched)
    return (
        df_features.set_index(["fire_name"]).to_crs(CRS_WGS84),
        df_unmatched.to_crs(CRS_WGS84),
    )


def override_fires(df_fires, df_override):
    # override df_fires when they match
    matched = list(set(df_override.index).intersection(set(df_fires.index)))
    unmatched = list(set(df_override.index).difference(set(matched)))
    if unmatched:
        logging.warning(f"Ignoring unmatched fires:\n{df_override.loc[unmatched]}")
    df_fires = df_fires.loc[:]
    df_override = df_override.loc[:]
    cols_missing = [x for x in df_override.columns if np.all(df_override[x].isna())]
    df_override.loc[matched, cols_missing] = df_fires.loc[matched, cols_missing]
    df_fires.loc[matched] = df_override.loc[matched]
    df_fires.loc[matched, "datetime"] = pick_max_by_column(
        df_fires, df_override, "datetime", matched
    )
    return df_fires


def find_sources_in_module(module, class_type):
    import importlib
    import inspect

    module = importlib.import_module(module)
    classes = [
        y for y in [getattr(module, x) for x in dir(module)] if inspect.isclass(y)
    ]
    return [
        c for c in classes if (issubclass(c, class_type) and not inspect.isabstract(c))
    ]


def find_sources(class_type, dir_search="private"):
    path = os.path.join(DIR_SRC_PY_FIRSTARR, "datasources", dir_search)
    if not os.path.isdir(path):
        return []
    files = [f.replace(".py", "") for f in listdir_sorted(path) if f.endswith(".py")]
    modules = [f"datasources.{dir_search.replace('/', '.')}.{f}" for f in files]
    from itertools import chain

    return list(
        chain.from_iterable([find_sources_in_module(m, class_type) for m in modules])
    )


class SourceFireActive(SourceFire):
    def __init__(
        self, dir_out, status_include=None, status_omit=["OUT"], year=YEAR
    ) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._status_include = status_include
        self._status_omit = status_omit
        self._source_ciffc = SourceFireCiffc(dir_out, status_ignore=None, year=year)
        # sources for features that we don't have a fire attached to
        self._source_features = [
            SourceFeatureM3(self._dir_out),
        ] + [s(self._dir_out) for s in find_sources(SourceFeature)]
        # sources for features that area associated with specific fires
        self._source_fires = [s(self._dir_out) for s in find_sources(SourceFire)]

    @cache
    def _get_fires(self):
        df_ciffc = self._source_ciffc.get_fires()
        df_fires = df_ciffc.loc[:]
        df_unmatched = None
        # override with each source in the order they appear
        for src in self._source_features:
            df_src = src.get_features()
            df_src_fires, df_unmatched_cur = assign_fires(df_src, df_fires)
            df_unmatched = pd.concat([df_unmatched, df_unmatched_cur])
            df_fires = override_fires(df_fires, df_src_fires)
        for src in self._source_fires:
            df_src_fires = src.get_fires()
            df_fires = override_fires(df_fires, df_src_fires)
        df_fires = df_fires.reset_index()
        logging.info(
            "Have %d polygons that are not tied to a fire",
            len(df_unmatched),
        )
        if self._status_include:
            df_fires = df_fires.loc[df_fires.status.isin(self._status_include)]
            logging.info(
                "Have %d features that are tied to %s fires",
                len(df_fires),
                self._status_include,
            )
        if self._status_omit:
            df_fires = df_fires.loc[~df_fires.status.isin(self._status_omit)]
            logging.info(
                "Have %d features that aren't tied to %s fires",
                len(df_fires),
                self._status_omit,
            )
        df_points = df_fires.loc[df_fires.geometry.type == "Point"].to_crs(
            CRS_COMPARISON
        )
        logging.info("Found %d fires that aren't matched with polygons", len(df_points))
        # HACK: put in circles of proper area if no perimeter
        df_points["geometry"] = df_points.apply(
            lambda x: x.geometry.buffer(
                max(0.1, area_ha_to_radius_m(max(0, x["area"])))
            ),
            axis=1,
        )
        df_fires.loc[df_points.index, "geometry"] = df_points.to_crs(CRS_WGS84)[
            "geometry"
        ]
        # pretty sure U is unknown status
        df_unmatched["status"] = "U"
        df_unmatched["fire_name"] = [f"UNMATCHED_{x}" for x in df_unmatched.index]
        df_all = pd.concat([df_fires, df_unmatched])
        return df_all


def wx_interpolate(df):
    date_min = df["datetime"].min()
    date_max = df["datetime"].max()
    times = pd.DataFrame(
        pd.date_range(date_min, date_max, freq="H").values, columns=["datetime"]
    )
    index_names = df.index.names
    groups = []
    for i, g in df.groupby(index_names):
        g_fill = pd.merge(times, g, how="left")
        # treat rain as if it all happened at start of any gaps
        g_fill["precip"] = g_fill["precip"].fillna(0)
        g_fill = g_fill.fillna(method="ffill")
        g_fill[index_names] = i
        groups.append(g_fill)
    df_filled = pd.concat(groups)
    df_filled.set_index(index_names)
    return df_filled
