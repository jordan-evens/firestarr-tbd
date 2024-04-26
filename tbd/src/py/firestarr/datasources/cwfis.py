import datetime
import os
from collections import Counter
from functools import cache

import model_data
import pandas as pd
import tqdm_util
from common import (
    DEFAULT_LAST_ACTIVE_SINCE_OFFSET,
    FMT_DATE_YMD,
    USE_CWFIS_SERVICE,
    logging,
    read_csv_safe,
    to_utc,
)
from datasources.datatypes import (
    SourceFeature,
    SourceFire,
    SourceFwi,
    make_point,
    make_template_empty,
)
from gis import CRS_COMPARISON, CRS_WGS84, read_gpd_file_safe, to_gdf
from model_data import DEFAULT_STATUS_IGNORE, URL_CWFIS_DOWNLOADS, make_query_geoserver
from net import try_save_http

WFS_CIFFC = "https://geoserver.ciffc.net/geoserver/wfs?version=2.0.0"


class SourceFeatureM3Service(SourceFeature):
    def __init__(self, dir_out, last_active_since) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out
        self._last_active_since = last_active_since
        # HACK: too much data if not limited
        date_recent = to_utc(datetime.date.today() - datetime.timedelta(days=30))
        if not self._last_active_since or self._last_active_since < date_recent:
            self._last_active_since = date_recent

    @cache
    def _get_features(self):
        save_as = f"{self._dir_out}/m3_polygons.json"
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
            df = read_gpd_file_safe(_)
            df["datetime"] = to_utc(df["lastdate"])
            since = pd.to_datetime(self._last_active_since, utc=True)
            return df.loc[df["datetime"] >= since]

        return try_save_http(
            make_query_geoserver(table_name, features=features, filter=filter),
            save_as,
            False,
            None,
            do_parse,
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
                    keep_existing=True,
                    fct_pre_save=None,
                    fct_post_save=None,
                )
            gdf = read_gpd_file_safe(f)
            return gdf

        df = get_shp("perimeters")
        # HACK: if empty then no results returned so fill with today where missing
        df.loc[df["LASTDATE"].isna(), "LASTDATE"] = datetime.date.today()
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
            gdf = read_gpd_file_safe(_)
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

        return try_save_http(
            make_query_geoserver(self.TABLE_NAME, filter=filter),
            save_as,
            False,
            None,
            do_parse,
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
            gdf = read_gpd_file_safe(_)
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

        return try_save_http(
            make_query_geoserver(
                self.TABLE_NAME,
                filter=filter,
                wfs_root=WFS_CIFFC,
            ),
            save_as,
            False,
            None,
            do_parse,
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
        return make_template_empty("fwi")
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
            keep_existing=True,
            fct_pre_save=None,
            fct_post_save=lambda _: read_gpd_file_safe(_)[["aes", "wmo", "lat", "lon"]],
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
            df = read_csv_safe(_, skipinitialspace=True)
            df = df.loc[df["NAME"] != "NAME"]
            df.columns = [x.lower() for x in df.columns]
            df = df.loc[~df["ffmc"].isna()]
            df["wmo"] = df["wmo"].astype(str)
            df = pd.merge(df, stns, on=["aes", "wmo"])
            df = df[["lat", "lon"] + cls.columns]
            df["datetime"] = pd.to_datetime(date) + datetime.timedelta(hours=12)
            df = df.sort_values(["datetime", "lat", "lon"])
            return to_gdf(df)

        ymd = date.strftime(FMT_DATE_YMD)
        url = f"{URL_CWFIS_DOWNLOADS}/fwi_obs/current/cwfis_fwi_{ymd}.csv"
        stns = cls._get_stns(dir_out)

        return try_save_http(
            url,
            os.path.join(dir_out, os.path.basename(url)),
            keep_existing=True,
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
