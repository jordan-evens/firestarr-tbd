import datetime
import os
from collections import Counter
from functools import cache

import geopandas as gpd
import model_data
import numpy as np
import pandas as pd
import tqdm_util
from common import (
    DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS,
    DIR_SRC_PY_FIRSTARR,
    FMT_DATE_YMD,
    USE_CWFIS_SERVICE,
    listdir_sorted,
    logging,
    pick_max,
    pick_max_by_column,
    to_utc,
)
from datasources.datatypes import (
    SourceFeature,
    SourceFire,
    SourceFwi,
    get_columns,
    make_point,
)
from gis import (
    CRS_COMPARISON,
    CRS_WGS84,
    KM_TO_M,
    area_ha,
    area_ha_to_radius_m,
    make_empty_gdf,
    save_shp,
    to_gdf,
)
from model_data import DEFAULT_STATUS_IGNORE, URL_CWFIS_DOWNLOADS, try_query_geoserver
from net import try_save_http

WFS_CIFFC = "https://geoserver.ciffc.net/geoserver/wfs?version=2.0.0"
STATUS_RANK = ["OUT", "UC", "BH", "OC", "UNK"]
DEFAULT_LAST_ACTIVE_SINCE_OFFSET = None


class SourceFeatureM3Service(SourceFeature):
    def __init__(self, dir_out, last_active_since) -> None:
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
            # FIX: implement upper bound
            filter = (
                f"lastdate >= {self._last_active_since.strftime('%Y-%m-%d')}T00:00:00Z"
            )

        def do_parse(_):
            logging.debug(f"Reading {_}")
            df = gpd.read_file(_)
            df["datetime"] = to_utc(df["lastdate"])
            since = pd.to_datetime(self._last_active_since, utc=True)
            return df.loc[df["datetime"] >= since]

        return try_query_geoserver(
            table_name, f_out, features=features, filter=filter, fct_post_save=do_parse
        )


class SourceFeatureM3Download(SourceFeature):
    def __init__(self, dir_out, last_active_since) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._last_active_since = last_active_since

    @cache
    def _get_features(self):
        def get_shp(filename):
            for ext in ["dbf", "prj", "shx", "shp"]:
                url = f"{URL_CWFIS_DOWNLOADS}/hotspots/{filename}.{ext}"
                # HACK: relies on .shp being last in list
                f = try_save_http(
                    url,
                    os.path.join(self._dir_out, os.path.basename(url)),
                    keep_existing=False,
                    fct_pre_save=None,
                    fct_post_save=None,
                )
            gdf = gpd.read_file(f)
            return gdf

        df = get_shp("perimeters")
        df["datetime"] = to_utc(df["LASTDATE"])
        since = pd.to_datetime(self._last_active_since, utc=True)
        return df.loc[df["datetime"] >= since]


class SourceFeatureM3(SourceFeature):
    def __init__(
        self, dir_out, origin, last_active_since_offset=DEFAULT_LAST_ACTIVE_SINCE_OFFSET
    ) -> None:
        super().__init__(bounds=None)
        self._origin = origin
        self._dir_out = dir_out
        # either use number of days or get everything for this year
        self._last_active_since = (
            self._origin.offset(-last_active_since_offset)
            if last_active_since_offset is not None
            else datetime.date(self._origin.today.year, 1, 1)
        )
        self._source = (
            SourceFeatureM3Service if USE_CWFIS_SERVICE else SourceFeatureM3Download
        )(self._dir_out, self._last_active_since)

    def _get_features(self):
        return self._source.get_features()


def make_name_ciffc(df):
    def make_name(date, agency, fire):
        return f"{date.year}_{agency.upper()}_{fire}"

    return tqdm_util.apply(
        df,
        lambda x: make_name(
            x["datetime"], x["field_agency_code"], x["field_agency_fire_id"]
        ),
        desc="Generating names",
    )


class SourceFireDipService(SourceFire):
    TABLE_NAME = "public:activefires"

    def __init__(self, dir_out, year, status_ignore=DEFAULT_STATUS_IGNORE) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._status_ignore = [] if status_ignore is None else status_ignore
        self._year = year

    @cache
    def _get_fires(self):
        save_as = f"{self._dir_out}/dip_current.json"

        filter = " and ".join(
            [f"\"stage_of_control\"<>'{status}'" for status in self._status_ignore]
            + [
                "agency<>'ak'",
                "agency<>'conus'",
                f"startdate during {self._year}-01-01T00:00:00Z/P1Y",
            ]
        )

        def do_parse(_):
            gdf = gpd.read_file(_)
            # only get latest status for each fire
            gdf = gdf.iloc[gdf.groupby(["firename"])["last_rep_date"].idxmax()]
            gdf = gdf.rename(
                columns={
                    "stage_of_control": "status",
                    "firename": "field_agency_fire_id",
                    "hectares": "area",
                    "last_rep_date": "datetime",
                    "agency": "field_agency_code",
                }
            )
            gdf["fire_name"] = make_name_ciffc(gdf)
            gdf = gdf.to_crs(CRS_WGS84)
            return gdf

        return try_query_geoserver(
            self.TABLE_NAME, save_as, filter=filter, fct_post_save=do_parse
        )


class SourceFireCiffcService(SourceFire):
    TABLE_NAME = "ciffc:ytd_fires"

    def __init__(self, dir_out, year, status_ignore=DEFAULT_STATUS_IGNORE) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._status_ignore = [] if status_ignore is None else status_ignore
        self._year = year

    @cache
    def _get_fires(self):
        save_as = f"{self._dir_out}/ciffc_current.json"
        filter = (
            " and ".join(
                [
                    f"\"field_stage_of_control_status\"<>'{status}'"
                    for status in self._status_ignore
                ]
            )
            or None
        )

        def do_parse(_):
            gdf = gpd.read_file(_)
            gdf = gdf.rename(
                columns={
                    "field_status_date": "datetime",
                    "field_stage_of_control_status": "status",
                    "field_fire_size": "area",
                }
            )
            gdf["datetime"] = pd.to_datetime(gdf["datetime"], errors="coerce")
            gdf["fire_name"] = make_name_ciffc(gdf)
            gdf = gdf.loc[gdf["datetime"].apply(lambda x: x.year) == self._year]
            gdf = gdf.set_index(["fire_name"])
            dupes = [
                k for k, v in Counter(gdf.reset_index()["fire_name"]).items() if v > 1
            ]
            df_dupes = gdf.loc[dupes].reset_index()
            gdf = gdf.drop(dupes)
            df_dupes.sort_values(["fire_name", "datetime", "area"], ascending=False)[
                ["fire_name", "datetime", "area", "status"]
            ]
            df_pick = (
                df_dupes.sort_values(["fire_name", "datetime", "area"], ascending=False)
                .groupby(["fire_name"])
                .first()
            )
            df_pick.crs = df_dupes.crs
            gdf = pd.concat([gdf, df_pick])
            return gdf

        return try_query_geoserver(
            self.TABLE_NAME,
            save_as,
            filter=filter,
            wfs_root=WFS_CIFFC,
            fct_post_save=do_parse,
        )


class SourceFireCiffc(SourceFire):
    def __init__(self, dir_out, year, status_ignore=DEFAULT_STATUS_IGNORE) -> None:
        super().__init__(bounds=None)
        self._source_ciffc = SourceFireCiffcService(dir_out, year, status_ignore)
        self._source_dip = SourceFireDipService(dir_out, year, status_ignore)

    def _get_fires(self):
        try:
            return self._source_ciffc.get_fires()
        except KeyboardInterrupt as ex:
            raise ex
        except Exception:
            return self._source_dip.get_fires()


def select_fwi(lat, lon, df_wx, columns):
    if df_wx is None:
        return make_empty_gdf(get_columns("fwi")[1])
    if 0 < len(df_wx):
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
    URL_STNS = f"{URL_CWFIS_DOWNLOADS}/fwi_obs/cwfis_allstn2022.csv"

    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._have_dates = {}

    @classmethod
    @cache
    def _get_stns(cls, dir_out):
        return try_save_http(
            cls.URL_STNS,
            os.path.join(dir_out, os.path.basename(cls.URL_STNS)),
            keep_existing=False,
            fct_pre_save=None,
            fct_post_save=lambda _: gpd.read_file(_)[["aes", "wmo", "lat", "lon"]],
        )

    @classmethod
    @cache
    def _get_wx_base(
        cls,
        dir_out,
        date,
    ):
        def do_parse(_):
            if _ is None:
                return None
            logging.debug("Reading {}".format(_))
            df = pd.read_csv(_, skipinitialspace=True)
            df = df.loc[df["NAME"] != "NAME"]
            df.columns = [x.lower() for x in df.columns]
            df = df.loc[~df["ffmc"].isna()]
            df["wmo"] = df["wmo"].astype(str)
            df = pd.merge(df, stns, on=["aes", "wmo"])
            df = df[["lat", "lon"] + cls.columns]
            df["datetime"] = date + datetime.timedelta(hours=12)
            df = df.sort_values(["datetime", "lat", "lon"])
            return to_gdf(df)

        ymd = date.strftime(FMT_DATE_YMD)
        url = f"{URL_CWFIS_DOWNLOADS}/fwi_obs/current/cwfis_fwi_{ymd}.csv"
        stns = cls._get_stns(dir_out)

        return try_save_http(
            url,
            os.path.join(dir_out, os.path.basename(url)),
            keep_existing=False,
            fct_pre_save=None,
            fct_post_save=do_parse,
            check_code=True,
        )

    def _get_fwi(self, lat, lon, date):
        return select_fwi(
            lat, lon, self._get_wx_base(self._dir_out, date), self.columns
        )


class SourceFwiCwfisService(SourceFwi):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out

    def _get_fwi(self, lat, lon, date):
        df_wx = model_data.get_wx_cwfis(
            self._dir_out, date, indices=",".join(self.columns)
        )
        return select_fwi(lat, lon, df_wx, self.columns)


class SourceFwiCwfis(SourceFwi):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._source = (
            SourceFwiCwfisService(dir_out)
            if USE_CWFIS_SERVICE
            else SourceFwiCwfisDownload(dir_out)
        )

    def _get_fwi(self, lat, lon, date):
        return self._source.get_fwi(lat, lon, date)


def find_rank(x):
    # rank is highest if unknown value
    return STATUS_RANK.index(x) if x in STATUS_RANK else (len(STATUS_RANK) - 1)


def assign_fires(
    origin,
    df_features,
    df_fires,
    days_to_keep_unmatched=DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS,
):
    # do this to make an index column
    df_features = df_features.reset_index().to_crs(CRS_COMPARISON)
    df_fires = df_fires.reset_index().to_crs(CRS_COMPARISON)
    df_join = df_features.sjoin_nearest(df_fires, how="left", max_distance=1 * KM_TO_M)
    df_join["status_rank"] = tqdm_util.apply(
        df_join["status"], find_rank, desc="Ranking by status"
    )
    df_unmatched = df_join[df_join["fire_name"].isna()][
        ["datetime_left", "geometry"]
    ].rename(columns={"datetime_left": "datetime"})
    # HACK: if unmatched then ignore more readily based on age
    min_active = to_utc(origin.today - datetime.timedelta(days=days_to_keep_unmatched))
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
    # want to keep all the fires that geometries intersect circles for
    # so that we can replace all of their named entries
    df_status = df_join.loc[:]
    # assign highest status for any of overlapping fires to all fires that overlap
    df_status[["status", "status_rank"]] = df_first[["status", "status_rank"]].loc[
        df_status["index"]
    ]
    # dissolve by fire_name but use max so highest lastdate stays
    df_dissolve = df_status.dissolve(by="fire_name", aggfunc="max").reset_index()
    df_dissolve["datetime"] = pick_max(
        df_dissolve["datetime_left"], df_dissolve["datetime_right"]
    )
    # at this point we might have the same geometry for multiple fires, but that
    # just means they'll all get replaced with it and then the group dissolve
    # will take care of duplicates
    df_matched = df_dissolve[["fire_name", "datetime", "status", "geometry"]]
    df_features = df_matched.reset_index(drop=True)
    df_features["area"] = area_ha(df_features)
    df_unmatched["area"] = area_ha(df_unmatched)
    return (
        df_features.set_index(["fire_name"]).to_crs(CRS_WGS84),
        df_unmatched.to_crs(CRS_WGS84),
    )


def override_fires(df_fires, df_override):
    if df_override is not None and 0 < len(df_override):
        if df_fires.crs != df_override.crs:
            raise RuntimeError("Expected matching CRS for override_fires()")
        # override df_fires when they match
        matched = list(set(df_override.index).intersection(set(df_fires.index)))
        unmatched = list(set(df_override.index).difference(set(matched)))
        if unmatched:
            logging.warning(f"Ignoring unmatched fires:\n{df_override.loc[unmatched]}")
        df_fires = df_fires.loc[:]
        df_override = df_override.loc[:]
        cols_missing = [x for x in df_override.columns if np.all(df_override[x].isna())]
        if cols_missing:
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
        self,
        dir_out,
        origin,
        status_include=None,
        status_omit=["OUT"],
    ) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._origin = origin
        self._status_include = status_include
        self._status_omit = status_omit
        self._source_ciffc = SourceFireCiffc(
            dir_out, status_ignore=None, year=self._origin.today.year
        )
        # sources for features that we don't have a fire attached to
        self._source_features = [
            SourceFeatureM3(self._dir_out, self._origin),
        ] + [s(self._dir_out) for s in find_sources(SourceFeature)]
        # sources for features that area associated with specific fires
        self._source_fires = [s(self._dir_out) for s in find_sources(SourceFire)]

    @cache
    def _get_fires(self):
        def save_fires(df, file_root):
            df_points = df[df.geometry.type == "Point"]
            df_polygons = df[df.geometry.type != "Point"]
            if 0 < len(df_points):
                save_shp(
                    df_points,
                    os.path.join(self._dir_out, f"{file_root}_points"),
                )
            if 0 < len(df_polygons):
                save_shp(
                    df_polygons,
                    os.path.join(self._dir_out, f"{file_root}_polygons"),
                )

        df_ciffc = self._source_ciffc.get_fires()
        df_fires = df_ciffc.loc[:]
        save_shp(df_fires, os.path.join(self._dir_out, "df_fires_ciffc"))
        df_circles = df_fires.loc[df_fires.geometry.type == "Point"].to_crs(
            CRS_COMPARISON
        )
        # HACK: put in circles of proper area so spatial join should hopefully
        # overlap actual polygons
        df_circles["geometry"] = tqdm_util.apply(
            df_circles,
            lambda x: x.geometry.buffer(
                max(0.1, area_ha_to_radius_m(max(0, x["area"])))
            ),
            desc="Converting points with area to circles",
        ).simplify(100)
        df_circles = df_circles.to_crs(CRS_WGS84)
        save_shp(df_circles, os.path.join(self._dir_out, "df_fires_circles"))
        df_fires = df_circles.iloc[:]
        df_unmatched = None
        # override with each source in the order they appear
        for i, src in enumerate(self._source_features):
            df_src = src.get_features()
            save_fires(df_src, f"df_fires_from_feature_source_{i:02d}")
            df_src_fires, df_unmatched_cur = assign_fires(
                self._origin, df_src, df_fires
            )
            save_fires(df_src_fires, f"df_fires_assigned_feature_source_{i:02d}")
            save_fires(df_unmatched_cur, f"df_fires_umatched_feature_source_{i:02d}")
            df_unmatched = pd.concat([df_unmatched, df_unmatched_cur])
            df_fires = override_fires(df_fires, df_src_fires)
            save_fires(df_fires, f"df_fires_after_feature_source_{i:02d}")
        for i, src in enumerate(self._source_fires):
            df_src_fires = src.get_fires()
            save_fires(df_src, f"df_fires_from_fire_source_{i:02d}")
            df_fires = override_fires(df_fires, df_src_fires)
            save_fires(df_fires, f"df_fires_after_fire_source_{i:02d}")
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
        save_fires(df_fires, "df_fires_after_status_include")
        if self._status_omit:
            df_fires = df_fires.loc[~df_fires.status.isin(self._status_omit)]
            logging.info(
                "Have %d features that aren't tied to %s fires",
                len(df_fires),
                self._status_omit,
            )
        save_fires(df_fires, "df_fires_after_status_omit")
        # pretty sure U is unknown status
        df_unmatched["status"] = "U"
        df_unmatched["fire_name"] = [f"UNMATCHED_{x}" for x in df_unmatched.index]
        df_all = pd.concat([df_fires, df_unmatched])
        save_fires(df_fires, "df_fires_after_concat")
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
