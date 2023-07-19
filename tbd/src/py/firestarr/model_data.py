import configparser
import datetime
import io
import os
import urllib

import geopandas as gpd
import numpy as np
import pandas as pd
from common import (
    CONFIG,
    CRS_LAMBERT_ATLAS,
    ParseError,
    get_http,
    logging,
    save_http,
    try_save,
)
from ratelimit import limits, sleep_and_retry

ONE_MINUTE = 60

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
    logging.debug(f"Getting table {table_name} in projection {str(CRS_LAMBERT_ATLAS)}")
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


def get_fires_m3(dir_out, last_active_since=datetime.date.today()):
    f_out = f"{dir_out}/m3_polygons.json"
    features = "uid,geometry,hcount,firstdate,lastdate,area,guess_id"
    table_name = "public:m3_polygons"
    if last_active_since:
        filter = f"lastdate >= {last_active_since.strftime('%Y-%m-%d')}T00:00:00Z"
    f_json = query_geoserver(table_name, f_out, features=features, filter=filter)
    logging.debug(f"Reading {f_json}")
    gdf = gpd.read_file(f_json)
    return gdf, f_json
    # fires_shp = f_out.replace('.json', '.shp')
    # gdf.to_file(fires_shp)
    # return gdf, fires_shp


# def get_fires_dip(dir_out, status_keep=DEFAULT_STATUS_KEEP):
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


# def get_fires_ciffc(dir_out, status_keep=DEFAULT_STATUS_KEEP):
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


def get_m3_download(dir_out, df_fires, last_active_since=datetime.date.today()):
    def get_shp(filename):
        for ext in ["dbf", "prj", "shx", "shp"]:
            url = f"https://cwfis.cfs.nrcan.gc.ca/downloads/hotspots/{filename}.{ext}"
            f_out = os.path.join(dir_out, os.path.basename(url))
            f = try_save(lambda _: save_http(_, f_out), url)
        gdf = gpd.read_file(f)
        return gdf

    perimeters = get_shp("perimeters")
    perimeters["LASTDATE"] = pd.to_datetime(perimeters["LASTDATE"])
    if last_active_since:
        perimeters = perimeters[
            perimeters["LASTDATE"] >= pd.to_datetime(last_active_since)
        ]
    # hotspots = get_shp("hotspots")
    # don't have guess_id
    df_perims = perimeters.to_crs(CRS_LAMBERT_ATLAS)
    perimeters = perimeters.to_crs(CRS_LAMBERT_ATLAS)
    df_fires = df_fires.to_crs(df_perims.crs)
    df_join = df_fires.sjoin_nearest(df_perims, max_distance=1)
    groups = df_join.groupby(["UID"])
    STATUS_RANK = ["OUT", "UC", "BH", "OC", "UNK"]
    perimeters["guess_id"] = None

    def find_rank(x):
        # rank is highest if unknown value
        return STATUS_RANK.index(x) if x in STATUS_RANK else (len(STATUS_RANK) - 1)

    # use fire with highest ranking status
    for k, v in groups.groups.items():
        g = groups.get_group(k)[:]
        g["status"] = g["field_stage_of_control_status"].apply(find_rank)
        f = g.sort_values(["status"], ascending=False).iloc[0]
        perimeters.loc[perimeters["UID"] == k, "guess_id"] = f.field_agency_fire_id
    perimeters.columns = [x.lower() for x in perimeters.columns]
    perimeters = perimeters.rename(columns={"uid": "id"})
    return perimeters


def get_wx_cwfis_download(dir_out, dates, indices=""):
    url_stns = "https://cwfis.cfs.nrcan.gc.ca/downloads/fwi_obs/cwfis_allstn2022.csv"
    stns = try_save(
        lambda _: save_http(_, os.path.join(dir_out, os.path.basename(url_stns))),
        url_stns,
    )
    gdf_stns = gpd.read_file(stns)
    stns = gdf_stns[["aes", "wmo", "lat", "lon"]]
    df = pd.DataFrame()
    for date in dates:
        ymd = date.strftime("%Y%m%d")
        url = f"{URL_DOWNLOADS}/fwi_obs/current/cwfis_fwi_{ymd}.csv"
        year = date.year
        month = date.month
        day = date.day
        file_out = os.path.join(
            dir_out, "{:04d}-{:02d}-{:02d}.csv".format(year, month, day)
        )
        if not os.path.exists(file_out):
            file_out = try_save(lambda _: save_http(_, file_out), url)
        logging.debug("Reading {}".format(file_out))
        try:
            df_day = pd.read_csv(file_out, skipinitialspace=True)
            # HACK: remove extra header rows in source
            df_day = df_day[df_day["NAME"] != "NAME"]
            df_day = df_day[~df_day["FFMC"].isna()]
            df_day.columns = [x.lower() for x in df_day.columns]
            df_day = df_day.drop(["name", "agency", "opts", "calcstatus"], axis=1)
            # col_int = ["aes", "wmo"]
            if [ymd] != np.unique(df_day["repdate"]):
                raise RuntimeError("Wrong day returned")
            df_day = pd.merge(df_day, stns, on=["aes", "wmo"])
            df_day = df_day.drop(["aes", "wmo", "repdate"], axis=1).astype(float)
            df_day["date"] = date
            df = pd.concat([df, df_day])
        except KeyboardInterrupt as ex:
            raise ex
        except pd.errors.ParserError:
            logging.warning(f"Ignoring invalid file {file_out}")
    df["year"] = df.apply(lambda x: x["date"].year, axis=1)
    df["month"] = df.apply(lambda x: "{:02d}".format(x["date"].month), axis=1)
    df["day"] = df.apply(lambda x: "{:02d}".format(x["date"].day), axis=1)
    df = df.sort_values(["year", "month", "day", "lat", "lon"])
    # # from looking at wms capabilities
    # crs = 3978
    # gdf = gpd.GeoDataFrame(df, geometry=df['the_geom'], crs=crs)
    crs = "NAD83"
    # is there any reason to make actual geometry?
    gdf = gpd.GeoDataFrame(
        df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=crs
    )
    return gdf


def get_wx_cwfis(
    dir_out, dates, indices="temp,rh,ws,wdir,precip,ffmc,dmc,dc,bui,isi,fwi,dsr"
):
    # layer = 'public:firewx_stns_current'
    # HACK: use 2022 because it has 2023 in it right now
    layer = "public:firewx_stns_2022"
    df = pd.DataFrame()
    for date in dates:
        year = date.year
        month = date.month
        day = date.day
        file_out = os.path.join(
            dir_out, "{:04d}-{:02d}-{:02d}.csv".format(year, month, day)
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
        df_day = pd.read_csv(file_out)
        df = pd.concat([df, df_day])
    df["date"] = df.apply(
        lambda x: datetime.datetime.strptime(x["rep_date"], "%Y-%m-%dT%H:00:00"), axis=1
    )
    df["year"] = df.apply(lambda x: x["date"].year, axis=1)
    df["month"] = df.apply(lambda x: "{:02d}".format(x["date"].month), axis=1)
    df["day"] = df.apply(lambda x: "{:02d}".format(x["date"].day), axis=1)
    df = df.sort_values(["year", "month", "day", "lat", "lon"])
    # from looking at wms capabilities
    crs = CRS_LAMBERT_ATLAS
    gdf = gpd.GeoDataFrame(df, geometry=df["the_geom"], crs=crs)
    return gdf


def get_spotwx_key():
    try:
        key = CONFIG.get("SPOTWX_API_KEY", "")
    except configparser.NoSectionError:
        key = None
    if key is None or 0 == len(key):
        raise RuntimeError("spotwx api key is required")
    # get rid of any quotes that might be in settings file
    key = key.replace('"', "").replace("'", "")
    return key


def get_spotwx_limit():
    return int(CONFIG.get("SPOTWX_API_LIMIT"))


@sleep_and_retry
@limits(calls=get_spotwx_limit(), period=ONE_MINUTE)
def get_wx_ensembles(lat, lon):
    SPOTWX_KEY = get_spotwx_key()
    model = "geps"
    url = "https://spotwx.io/api.php3?" + "&".join(
        [
            f"key={SPOTWX_KEY}",
            f"model={model}",
            f"lat={round(lat, 3)}",
            f"lon={round(lon, 3)}",
            "ens_val=members",
        ]
    )
    logging.debug(url)

    def get_initial(url):
        content = get_http(url)
        content = str(content, encoding="utf-8")
        df_initial = pd.read_csv(io.StringIO(content))
        if "UTC_OFFSET" not in df_initial.columns:
            raise ParseError(content)
        return df_initial

    # HACK: wrap initial parse with this so it retries if we get a page that
    # isn't what we want back
    df_initial = try_save(get_initial, url, check_code=False)
    if list(np.unique(df_initial.UTC_OFFSET)) != [0]:
        raise RuntimeError("Expected weather in UTC time")
    index = ["MODEL", "LAT", "LON", "ISSUEDATE", "UTC_OFFSET", "DATETIME"]
    # all_cols = np.unique([x[: x.index("_")] for x in df_initial.columns if "_" in x])
    cols = ["TMP", "RH", "WSPD", "WDIR", "PRECIP"]
    keep_cols = [
        x
        for x in df_initial.columns
        if x in index or np.any([x.startswith(f"{_}_") for _ in cols])
    ]
    df_by_var = pd.melt(df_initial, id_vars=index, value_vars=keep_cols)
    df_by_var["var"] = df_by_var["variable"].apply(lambda x: x[: x.rindex("_")])
    df_by_var["id"] = [
        0 if "CONTROL" == id else int(id)
        for id in df_by_var["variable"].apply(lambda x: x[x.rindex("_") + 1 :])
    ]
    del df_by_var["variable"]
    df_wx = pd.pivot(
        df_by_var, index=index + ["id"], columns="var", values="value"
    ).reset_index()
    df_wx.groupby(["id"])["PRECIP_ttl"]
    df = None
    for i, g in df_wx.groupby(["id"]):
        g["PRECIP"] = (g["PRECIP_ttl"] - g["PRECIP_ttl"].shift(1)).fillna(0)
        df = pd.concat([df, g])
    # HACK: for some reason rain is less in subsequent hours sometimes, so make
    # sure nothing is negative
    df.loc[df["PRECIP"] < 0, "PRECIP"] = 0
    del df["PRECIP_ttl"]
    df = df.reset_index()
    del df["index"]
    df.columns.name = ""
    # make sure we're in UTC and use that for now
    assert [0] == np.unique(df["UTC_OFFSET"])
    df.columns = [x.lower() for x in df.columns]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.rename(columns={"tmp": "temp", "wdir": "wd", "wspd": "ws"})
    df["issuedate"] = pd.to_datetime(df["issuedate"])
    index_final = ["model", "lat", "lon", "issuedate", "id"]
    df = df[index_final + ["datetime", "temp", "rh", "wd", "ws", "precip"]]
    df = df.set_index(index_final)
    return df


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
