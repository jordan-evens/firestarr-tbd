import os

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely.geometry
from common import ensure_dir
from gis import CRS_WGS84

DIR = ensure_dir("../data/tmp/bounds")
KM_TO_M = 1000
BY_NAME = {}
BUFFER_RESOLUTION = 32


def to_file(df, name, dir=DIR):
    print(name)
    global BY_NAME
    if name in BY_NAME and df.equals(BY_NAME[name]):
        return df
    df_wgs84 = df.to_crs(CRS_WGS84)
    df_wgs84.to_file(os.path.join(dir, f"{name}.geojson"))
    df_wgs84.to_file(os.path.join(dir, f"{name}.shp"))
    try:
        print(dist(centroids_canada, centroids(dissolve(df).set_index(["EN"]))))
    except KeyboardInterrupt as ex:
        raise ex
    except Exception:
        print("problem comparing centroids")
    BY_NAME[name] = df
    return df


def to_envelope(df):
    df = df.iloc[:]
    df.geometry = df.envelope
    return df


def buffer(df, km, resolution=BUFFER_RESOLUTION):
    df = df.iloc[:]
    df.geometry = df.buffer(km * KM_TO_M, resolution=resolution)
    return df


def dissolve(df, by="ID"):
    return df.dissolve(by=by).reset_index().sort_values("EN")


def explode(df):
    return df.explode(index_parts=False)


def simplify(df, km):
    df = df.iloc[:]
    df.geometry = df.simplify(tolerance=km * KM_TO_M)
    return df


def convex_hull(df):
    df.geometry = df.convex_hull
    return df


def fill(df):
    df = df.iloc[:]
    for i in range(len(df)):
        b = df.iloc[i].geometry
        polys = [shapely.geometry.Polygon(x) for x in b.interiors]
        for p in polys:
            b = b.union(p)
        df.geometry.iloc[i] = b
    return df


def centroids(df):
    c = df.centroid
    return {idx: c.loc[idx] for idx in df.index}


def dist(c1, c2):
    assert c1.keys() == c2.keys()
    return np.sum([v.distance(c2[k]) for k, v in c1.items()])


if "__main__" == __name__:
    df_canada = gpd.read_file("../data/tmp/canada/lpr_000b16a_e.shp").sort_values(
        ["PRENAME"]
    )
    CRS_ORIG = df_canada.crs
    centroids_canada = centroids(df_canada.set_index(["PRENAME"]))

    df_bounds = to_file(
        gpd.read_file("bounds.geojson").sort_values(["EN"]).to_crs(CRS_ORIG),
        "df_bounds",
    )
    centroids_orig = centroids(df_bounds.set_index(["EN"]))

    df_bounds_exact = gpd.GeoDataFrame(
        pd.merge(
            df_bounds[[x for x in df_bounds.columns if x != "geometry"]],
            df_canada[["PRENAME", "geometry"]],
            left_on=["EN"],
            right_on=["PRENAME"],
        ),
        crs=CRS_ORIG,
    )
    centroids_exact = centroids(df_bounds_exact.set_index(["EN"]))
    assert centroids_exact == centroids_canada

    df = to_file(df_bounds_exact, "df_bounds_exact")

    df = to_file(explode(df), "df_explode")

    df = to_file(simplify(df, 1), "df_simplify")

    df = to_file(buffer(df, 100), "df_buffer")

    # df = to_file(simplify(df, 10), "df_buffer_simplify")

    df = to_file(dissolve(df), "df_buffer_simplify_dissolve")

    df = to_file(fill(df), "df_buffer_simplify_dissolve_fill")

    df = to_file(simplify(df, 10), "df_simplify_10km")

    df = to_file(simplify(df, 100), "df_simplify_100km")

    assert list(df["EN"]) == list(df_bounds["EN"])

    bounds = to_file(df, "bounds")

    bounds.reset_index()[
        ["ID", "EN", "FR", "PRIORITY", "DURATION", "geometry"]
    ].set_index(["ID"]).to_crs(CRS_WGS84).to_file("bounds.geojson")
