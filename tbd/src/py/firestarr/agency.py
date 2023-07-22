import geopandas as gpd
from gis import CRS_WGS84


def make_empty_gdf(columns):
    return gpd.GeoDataFrame({k: [] for k in columns + ["geometry"]}, crs=CRS_WGS84)


COLUMNS_MODEL = ["model", "id"]
COLUMNS_STATION = ["lat", "lon"]
COLUMN_TIME = "datetime"
COLUMNS = {
    # "fire": {"key": ["fire_name"], "columns": ["is_out"]},
    "fire": {"key": ["fire_name"], "columns": []},
    "fwi": {"key": COLUMNS_STATION, "columns": ["ffmc", "dmc", "dc"]},
    "weather": {
        "key": COLUMNS_MODEL + COLUMNS_STATION,
        "columns": ["temp", "rh", "wd", "ws", "precip"],
    },
}


def get_columns(template):
    t = COLUMNS[template]
    key = t["key"] + [COLUMN_TIME]
    columns = key + t["columns"] + ["geometry"]
    return key, columns


def check_columns(df, template):
    key, columns = get_columns(template)
    try:
        return df[columns].set_index(key)
    except KeyError:
        ERR = "Columns do not match expected columns"
        raise RuntimeError(f"{ERR}\nExpected:\n\t{columns}\nGot:\n\t{df.columns}")


def make_error(signature, template):
    key, columns = get_columns(template)
    raise NotImplementedError(
        f"Must implement {signature} returning columns:\n\t{columns}"
    )


def pick_date_refresh(as_of, refresh):
    # if from a previous date then use that, but if from same day as refresh
    # use refresh time
    return as_of if as_of.date() != refresh.date() else refresh


class AgencyData(object):
    def _get_fires(self):
        raise make_error("_get_fires()", "fire")

    def get_fires(self):
        return check_columns(self._get_fires(), "fire")

    def _get_wx_forecast(self, lat, lon):
        raise make_error("_get_wx_forecast(lat, lon)", "weather")

    def get_wx_forecast(self, lat, lon):
        return check_columns(self._get_wx_forecast(lat, lon), "weather")

    def _get_wx_hourly(self, lat, lon, datetime_start=None, datetime_end=None):
        signature = "_get_wx_hourly(lat, lon, datetime_start, datetime_end)"
        raise make_error(signature, "weather")

    def get_wx_hourly(self, lat, lon, datetime_start=None, datetime_end=None):
        return check_columns(
            self._get_wx_hourly(lat, lon, datetime_start, datetime_end), "weather"
        )

    def _get_fwi(self, lat, lon, datetime_start=None, datetime_end=None):
        signature = "_get_fwi(lat, lon, datetime_start, datetime_end)"
        raise make_error(signature, "fwi")

    def get_fwi(self, lat, lon, datetime_start=None, datetime_end=None):
        return check_columns(
            self._get_fwi(lat, lon, datetime_start, datetime_end), "fwi"
        )
