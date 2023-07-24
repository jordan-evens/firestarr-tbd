import datetime
import os
from functools import cache

import geopandas as gpd
import numpy as np
import pandas as pd
import tqdm_util
from common import BOUNDS, CONFIG, DIR_DOWNLOAD, do_nothing, ensure_dir, logging
from datasources.datatypes import SourceModel
from gis import to_gdf
from net import try_save_http
from pyrate_limiter import Duration, FileLockSQLiteBucket, Limiter, RequestRate

DIR_SPOTWX = ensure_dir(os.path.join(DIR_DOWNLOAD, "spotwx"))
COORDINATE_PRECISION = 2


def get_spotwx_key():
    key = CONFIG.get("SPOTWX_API_KEY", "")
    if not key:
        raise RuntimeError("spotwx api key is required")
    # get rid of any quotes that might be in settings file
    key = key.replace('"', "").replace("'", "")
    return key


def get_spotwx_limit():
    return int(CONFIG.get("SPOTWX_API_LIMIT"))
    # return 5


# NOTE: does not work with multiprocess unless bucket_class is set properly
limiter = Limiter(
    RequestRate(get_spotwx_limit(), Duration.MINUTE), bucket_class=FileLockSQLiteBucket
)


def limit_api(x):
    with limiter.ratelimit("limit_api", delay=True):
        return x


def make_spotwx_query(model, lat, lon, **kwargs):
    SPOTWX_KEY = get_spotwx_key()
    if not model:
        raise RuntimeError("No model specified")
    lat, lon = fix_coords(lat, lon)
    url = "https://spotwx.io/api.php?" + "&".join(
        [
            f"key={SPOTWX_KEY}",
            f"model={model}",
            f"lat={lat}",
            f"lon={lon}",
        ]
        + [f"{k}={v}" for k, v in kwargs.items()]
    )
    return url


def spotwx_parse(
    url, save_as, keep_existing, need_column, fct_process_df, expected_value=None
):
    def do_parse(_):
        df = pd.read_csv(_, encoding="utf-8")
        # df.columns = [x.lower for x in df.columns]
        valid = need_column in df.columns
        if valid:
            if expected_value:
                valid = list(np.unique(df[need_column])) == [expected_value]
        if not valid:
            with open(_) as f:
                for line in f.readlines():
                    if "api limit" in line.lower():
                        logging.fatal(line)
                        raise RuntimeError(line)
            str_suffix = f" with value {expected_value}" if expected_value else ""
            raise RuntimeError(f"Expected column {need_column}{str_suffix}")
        return (fct_process_df or do_nothing)(df)

    return try_save_http(
        url,
        save_as,
        keep_existing=keep_existing,
        fct_pre_save=limit_api,
        fct_post_save=do_parse,
    )


@cache
def get_model_time(model):
    # request middle of bounds since point shouldn't change model time
    lat = BOUNDS["latitude"]["mid"]
    lon = BOUNDS["longitude"]["mid"]
    url = make_spotwx_query(model, lat, lon, output="archive")
    save_as = os.path.join(DIR_SPOTWX, model, f"spotwx_{model}_current.csv")

    def do_parse(df):
        return np.max(
            df["modelrun"].apply(lambda x: datetime.datetime.strptime(x, "%Y%m%d_%HZ"))
        )

    return spotwx_parse(
        url,
        save_as,
        keep_existing=False,
        need_column="modelrun",
        fct_process_df=do_parse,
    )


@cache
def get_model_dir(model):
    model_time = get_model_time(model)
    return ensure_dir(
        os.path.join(DIR_SPOTWX, model, model_time.strftime("%Y%m%d_%HZ"))
    )


def get_rounding():
    return COORDINATE_PRECISION


def fix_coords(lat, lon):
    n = get_rounding()
    return round(lat, n), round(lon, n)


def fmt_rounded(x):
    n = get_rounding()
    return f"{x:0{n + 4}.{n}f}"


def make_filename(model, lat, lon, ext):
    return f"spotwx_{model}_{fmt_rounded(lat)}_{fmt_rounded(lon)}.{ext}"


def query_wx_ensembles(model, lat, lon):
    global COORDINATE_PRECISION
    dir_model = get_model_dir(model)
    # HACK: change precision after this run so that points don't round
    #       differently between runs as easily
    if dir_model and os.path.basename(dir_model) == "20230724_12Z":
        COORDINATE_PRECISION = 3
    url = make_spotwx_query(model, lat, lon, ens_val="members")
    save_as = os.path.join(dir_model, make_filename(model, lat, lon, "csv"))
    return spotwx_parse(
        url, save_as, keep_existing=True, need_column="UTC_OFFSET", fct_process_df=None
    )


@cache
def get_wx_ensembles(model, lat, lon):
    # only care about limiting queries - processing time doesn't matter
    df_initial = query_wx_ensembles(model, lat, lon)
    index = ["MODEL", "LAT", "LON", "ISSUEDATE", "UTC_OFFSET", "DATETIME"]
    # all_cols = np.unique([x[: x.index("_")] for x in df_initial.columns if "_" in x])
    cols = ["TMP", "RH", "WSPD", "WDIR", "PRECIP"]
    keep_cols = [
        x
        for x in df_initial.columns
        if x in index or np.any([x.startswith(f"{_}_") for _ in cols])
    ]
    df_by_var = pd.melt(df_initial, id_vars=index, value_vars=keep_cols)
    df_by_var["var"] = tqdm_util.apply(
        df_by_var["variable"],
        lambda x: x[: x.rindex("_")],
        desc="Separating by variable",
    )
    df_by_var["id"] = [
        0 if "CONTROL" == id else int(id)
        for id in tqdm_util.apply(
            df_by_var["variable"],
            lambda x: x[x.rindex("_") + 1 :],
            desc="Finding members",
        )
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
    if [0] != np.unique(df["UTC_OFFSET"]):
        raise RuntimeError("Expected UTC times")
    df.columns = [x.lower() for x in df.columns]
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.rename(columns={"tmp": "temp", "wdir": "wd", "wspd": "ws"})
    df["issuedate"] = pd.to_datetime(df["issuedate"])
    index_final = ["model", "lat", "lon", "issuedate", "id"]
    df = df[index_final + ["datetime", "temp", "rh", "wd", "ws", "precip"]]
    df = df.set_index(index_final)
    return df


class SourceGEPS(SourceModel):
    def __init__(self, dir_out) -> None:
        super().__init__(bounds=None)
        self._dir_out = dir_out

    @classmethod
    @property
    def model(cls):
        return "geps"

    def _get_wx_model(self, lat, lon):
        file_out = os.path.join(
            self._dir_out, make_filename(self.model, lat, lon, "geojson")
        )
        if not os.path.isfile(file_out):
            gdf = to_gdf(get_wx_ensembles(self.model, lat, lon).reset_index())
            gdf.to_file(file_out)
        return gpd.read_file(file_out)
