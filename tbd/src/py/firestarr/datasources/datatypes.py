from abc import ABC, abstractmethod

import geopandas as gpd
import numpy as np
from common import CRS_COMPARISON, CRS_WGS84


def make_empty_gdf(columns):
    return gpd.GeoDataFrame({k: [] for k in columns + ["geometry"]}, crs=CRS_WGS84)


COLUMNS_MODEL = ["model", "id"]
COLUMNS_STATION = ["lat", "lon"]
COLUMN_TIME = "datetime"
COLUMNS = {
    "feature": {"key": [], "columns": []},
    "fire": {"key": ["fire_name"], "columns": ["area", "status"]},
    "fwi": {"key": COLUMNS_STATION, "columns": ["ffmc", "dmc", "dc"]},
    "weather": {
        "key": COLUMNS_MODEL + COLUMNS_STATION,
        "columns": ["temp", "rh", "wd", "ws", "precip"],
    },
}


def get_columns(template):
    t = COLUMNS[template]
    key = t["key"]
    columns = key + [COLUMN_TIME] + t["columns"] + ["geometry"]
    return key, columns


def check_columns(df, template):
    key, columns = get_columns(template)
    try:
        # sort based on columns in order from left to right
        df = df.reset_index()[columns].sort_values(columns)
        if key:
            df = df.set_index(key)
        else:
            # renumber rows if no key
            df = df.reset_index(drop=True)
        # HACK: keep everything in WGS84
        if isinstance(df, gpd.GeoDataFrame):
            df = df.to_crs(CRS_WGS84)
        return df
    except KeyError:
        ERR = "Columns do not match expected columns"
        raise RuntimeError(f"{ERR}\nExpected:\n\t{columns}\nGot:\n\t{df.columns}")


def to_gdf(df, crs=CRS_WGS84):
    return gpd.GeoDataFrame(
        df, crs=crs, geometry=gpd.points_from_xy(df["lon"], df["lat"], crs=crs)
    )


def make_point(lat, lon, crs=CRS_WGS84):
    # always take lat lon as WGS84 but project to requested crs
    pt = gpd.points_from_xy([lon], [lat], crs=CRS_WGS84)
    if crs != CRS_WGS84:
        pt = gpd.GeoDataFrame(geometry=pt, crs=CRS_WGS84).to_crs(crs).iloc[0].geometry
    return pt


def find_closest(df, lat, lon, crs=CRS_COMPARISON):
    df["dist"] = df.to_crs(crs).distance(make_point(lat, lon, crs))
    return df.loc[df["dist"] == np.min(df["dist"])]


def make_error(signature, template):
    key, columns = get_columns(template)
    raise NotImplementedError(
        f"Must implement {signature} returning columns:\n\t{columns}"
    )


def pick_date_refresh(as_of, refresh):
    # if from a previous date then use that, but if from same day as refresh
    # use refresh time
    return as_of if as_of.date() != refresh.date() else refresh


class Source(ABC):
    def __init__(self, provides, bounds) -> None:
        self._provides = provides
        # this applies to anything in the bounds
        self._bounds = bounds if bounds is None else bounds.dissolve()

    @property
    def provides(self):
        return self._provides

    @property
    def bounds(self) -> gpd.GeoDataFrame:
        # copy so it can't be modified
        return None if self._bounds is None else self._bounds.loc[:]

    def applies_to(self, lat, lon) -> bool:
        return self._bounds is None or self._bounds.contains(
            make_point(lat, lon, self._bounds.crs)
        )


class SourceFeature(Source):
    def __init__(self, bounds) -> None:
        super().__init__("feature", bounds)

    @abstractmethod
    def _get_features(self):
        raise make_error("_get_features()", "feature")

    def get_features(self):
        return check_columns(self._get_features(), "feature")


class SourceFire(Source):
    def __init__(self, bounds) -> None:
        super().__init__("fire", bounds)

    @abstractmethod
    def _get_fires(self):
        raise make_error("_get_fires()", "fire")

    def get_fires(self):
        return check_columns(self._get_fires(), "fire")


class SourceModel(Source):
    def __init__(self, bounds) -> None:
        super().__init__("model", bounds)

    @abstractmethod
    def _get_wx_model(self, lat, lon):
        raise make_error("_get_wx_model(lat, lon)", "weather")

    def get_wx_model(self, lat, lon):
        return check_columns(self._get_wx_model(lat, lon), "weather")


class SourceHourly(Source):
    def __init__(self, bounds) -> None:
        super().__init__("hourly", bounds)

    @abstractmethod
    def _get_wx_hourly(self, lat, lon, datetime_start=None, datetime_end=None):
        signature = "_get_wx_hourly(lat, lon, datetime_start, datetime_end)"
        raise make_error(signature, "weather")

    def get_wx_hourly(self, lat, lon, datetime_start=None, datetime_end=None):
        return check_columns(
            self._get_wx_hourly(lat, lon, datetime_start, datetime_end), "weather"
        )


class SourceFwi(Source):
    def __init__(self, bounds) -> None:
        super().__init__("fwi", bounds)

    @abstractmethod
    def _get_fwi(self, lat, lon, datetime_start=None, datetime_end=None):
        signature = "_get_fwi(lat, lon, datetime_start, datetime_end)"
        raise make_error(signature, "fwi")

    def get_fwi(self, lat, lon, datetime_start=None, datetime_end=None):
        return check_columns(
            self._get_fwi(lat, lon, datetime_start, datetime_end), "fwi"
        )
