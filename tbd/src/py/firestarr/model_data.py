import datetime
import os
import urllib
from functools import cache

import geopandas as gpd
from gis import CRS_COMPARISON, to_gdf
import pandas as pd
from common import FMT_DATE, logging, save_http, try_save

WFS_ROOT = (
    "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wms?service=wfs&version=2.0.0"
)
WFS_CIFFC = "https://geoserver.ciffc.net/geoserver/wfs?version=2.0.0"
DEFAULT_STATUS_IGNORE = ["OUT", "UC", "BH", "U"]
# DEFAULT_STATUS_KEEP = ["OC"]
URL_DOWNLOADS = "https://cwfis.cfs.nrcan.gc.ca/downloads"


def query_geoserver(
    table_name,
    f_out,
    features=None,
    filter=None,
    wfs_root=WFS_ROOT,
    output_format="application/json",
):
    logging.debug(f"Getting table {table_name} in projection {str(CRS_COMPARISON)}")
    request_url = "&".join(
        [
            f"{wfs_root}&request=GetFeature",
            f"typename={table_name}",
            f"outputFormat={output_format}",
        ]
    )
    if features is not None:
        request_url += f"&propertyName={features}"
    if filter is not None:
        request_url += f"&CQL_FILTER={urllib.parse.quote(filter)}"
    logging.debug(request_url)
    return try_save(
        lambda _: save_http(
            _, save_as=f_out, check_modified=False, ignore_existing=False
        ),
        request_url,
        check_code=False,
    )


@cache
def get_fires_dip(
    dir_out, status_ignore=DEFAULT_STATUS_IGNORE, year=datetime.date.today().year
):
    f_out = f"{dir_out}/dip_current.json"
    table_name = "public:activefires"
    # features = "*"
    features = None
    # filter = None
    if status_ignore is None:
        status_ignore = []
    filter = " and ".join(
        [f"\"stage_of_control\"<>'{status}'" for status in status_ignore]
        + [
            #   "current=true",
            "agency<>'ak'",
            "agency<>'conus'",
            f"startdate during {year}-01-01T00:00:00Z/P1Y",
        ]
    )
    f_json = query_geoserver(table_name, f_out, features=features, filter=filter)
    gdf = gpd.read_file(f_json)
    # only get latest status for each fire
    gdf = gdf.iloc[gdf.groupby(["firename"])["last_rep_date"].idxmax()]
    return gdf, f_json


@cache
def get_fires_ciffc(dir_out, status_ignore=DEFAULT_STATUS_IGNORE):
    table_name = "ciffc:ytd_fires"
    f_out = f"{dir_out}/ciffc_current.json"
    # features = "*"
    features = None
    # filter = None
    if status_ignore is None:
        status_ignore = []
    filter = (
        " and ".join(
            [
                f"\"field_stage_of_control_status\"<>'{status}'"
                for status in status_ignore
            ]
        )
        or None
    )
    f_json = query_geoserver(
        table_name, f_out, features=features, filter=filter, wfs_root=WFS_CIFFC
    )
    gdf = gpd.read_file(f_json)
    return gdf, f_json


@cache
def get_wx_cwfis_download_stns(dir_out):
    url_stns = "https://cwfis.cfs.nrcan.gc.ca/downloads/fwi_obs/cwfis_allstn2022.csv"
    stns = try_save(
        lambda _: save_http(_, os.path.join(dir_out, os.path.basename(url_stns))),
        url_stns,
    )
    gdf_stns = gpd.read_file(stns)
    stns = gdf_stns[["aes", "wmo", "lat", "lon"]]
    return stns


@cache
def get_wx_cwfis_download(
    dir_out, date, indices="temp,rh,ws,wdir,precip,ffmc,dmc,dc,bui,isi,fwi,dsr"
):
    stns = get_wx_cwfis_download_stns(dir_out)
    ymd = date.strftime(FMT_DATE)
    url = f"{URL_DOWNLOADS}/fwi_obs/current/cwfis_fwi_{ymd}.csv"
    year = date.year
    month = date.month
    day = date.day
    file_out = os.path.join(
        dir_out, "cwfis_download_{:04d}-{:02d}-{:02d}.csv".format(year, month, day)
    )
    if not os.path.exists(file_out):
        file_out = try_save(lambda _: save_http(_, file_out), url)
    logging.debug("Reading {}".format(file_out))
    df = pd.read_csv(file_out, skipinitialspace=True)
    df = df.loc[df["NAME"] != "NAME"]
    df.columns = [x.lower() for x in df.columns]
    df = df.loc[~df["ffmc"].isna()]
    df["wmo"] = df["wmo"].astype(str)
    df = pd.merge(df, stns, on=["aes", "wmo"])
    df = df[["lat", "lon"] + indices.split(",")]
    # df = df.drop(["aes", "wmo", "repdate"], axis=1).astype(float)
    df["datetime"] = date
    df = df.sort_values(["datetime", "lat", "lon"])
    gdf = to_gdf(df)
    return gdf


@cache
def get_wx_cwfis(
    dir_out, date, indices="temp,rh,ws,wdir,precip,ffmc,dmc,dc,bui,isi,fwi,dsr"
):
    # layer = 'public:firewx_stns_current'
    # HACK: use 2022 because it has 2023 in it right now
    layer = "public:firewx_stns_2022"
    year = date.year
    month = date.month
    day = date.day
    file_out = os.path.join(
        dir_out, "cwfis_layer_{:04d}-{:02d}-{:02d}.csv".format(year, month, day)
    )
    if not os.path.exists(file_out):
        file_out = query_geoserver(
            layer,
            file_out,
            features=f"rep_date,prov,lat,lon,elev,the_geom,{indices}",
            filter=f"rep_date={year:04d}-{month:02d}-{day:02d}T12:00:00",
            output_format="csv",
        )
    logging.debug("Reading {}".format(file_out))
    df = pd.read_csv(file_out)
    df["datetime"] = df.apply(
        lambda x: datetime.datetime.strptime(x["rep_date"], "%Y-%m-%dT%H:00:00"), axis=1
    )
    df = df[["lat", "lon"] + indices.split(",") + ["datetime"]]
    df = df.sort_values(["datetime", "lat", "lon"])
    gdf = to_gdf(df)
    return gdf


def wx_interpolate(df):
    date_min = df["datetime"].min()
    date_max = df["datetime"].max()
    times = pd.DataFrame(
        pd.date_range(date_min, date_max, freq="H").values, columns=["datetime"]
    )
    crs = df.crs
    index_names = df.index.names
    df = df.reset_index()
    idx_geom = ["lat", "lon", "geometry"]
    gdf_geom = df[idx_geom].drop_duplicates().reset_index(drop=True)
    del df["geometry"]
    groups = []
    for i, g in df.groupby(index_names):
        g_fill = pd.merge(times, g, how="left")
        # treat rain as if it all happened at start of any gaps
        g_fill["precip"] = g_fill["precip"].fillna(0)
        g_fill = g_fill.fillna(method="ffill")
        g_fill[index_names] = i
        groups.append(g_fill)
    df_filled = to_gdf(pd.merge(pd.concat(groups), gdf_geom), crs)
    df_filled.set_index(index_names)
    return df_filled
