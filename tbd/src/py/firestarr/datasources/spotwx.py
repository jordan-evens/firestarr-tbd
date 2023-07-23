import configparser
from functools import cache
import io
from gis import to_gdf

import numpy as np
import pandas as pd
from common import CONFIG, ParseError, get_http, logging, try_save
from datasources.datatypes import SourceModel
from ratelimit import limits, sleep_and_retry

ONE_MINUTE = 60


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
def query_wx_ensembles(lat, lon):
    SPOTWX_KEY = get_spotwx_key()
    model = "geps"
    url = "https://spotwx.io/api.php?" + "&".join(
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
    return df_initial


@cache
def get_wx_ensembles(lat, lon):
    # only care about limiting queries - processing time doesn't matter
    df_initial = query_wx_ensembles(lat, lon)
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


class SourceGEPS(SourceModel):
    def __init__(self) -> None:
        super().__init__(bounds=None)

    def _get_wx_model(self, lat, lon):
        return to_gdf(get_wx_ensembles(lat, lon).reset_index())
