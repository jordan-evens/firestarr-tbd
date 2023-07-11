import sys
sys.path.append('../util')
from common import *
import geopandas as gpd
import shapely.geometry

DIR = ensure_dir('../data/tmp/bounds')
CRS = 'WGS84'
KM_TO_M = 1000


def to_file(df, name, dir=DIR):
    print(name)
    df.to_file(os.path.join(dir, f"{name}.geojson"))
    df.to_file(os.path.join(dir, f"{name}.shp"))
    return df


def to_envelope(df):
    df = df.to_crs(CRS_ORIG)
    df.geometry = df.envelope
    return df.to_crs(CRS)


def buffer(df, km):
    df = df.to_crs(CRS_ORIG)
    df.geometry = df.buffer(km * KM_TO_M)
    return df.to_crs(CRS)


def dissolve(df):
    return df.dissolve(by='ID')


def simplify(df, km):
    df = df.to_crs(CRS_ORIG)
    df.geometry = df.simplify(tolerance=km * KM_TO_M)
    return df.to_crs(CRS)


def convex_hull(df):
    df = df.to_crs(CRS_ORIG)
    df.geometry = df.convex_hull
    return df.to_crs(CRS)


def fill(df):
    df = df.iloc[:]
    for i in range(len(df)):
        b = df.iloc[i].geometry
        polys = [shapely.geometry.Polygon(x) for x in b.interiors]
        for p in polys:
            b = b.union(p)
        df.geometry.iloc[i] = b
    return df


df_bounds = to_file(gpd.read_file('bounds.geojson').sort_values(['EN']), "df_bounds")

df_canada = gpd.read_file('../data/tmp/canada/lpr_000b16a_e.shp').sort_values(['PRENAME'])
CRS_ORIG = df_canada.crs
df_canada_wgs84 = df_canada.to_crs(CRS)
df_bounds_exact = df_bounds.iloc[:]
df_bounds_exact.geometry = df_canada_wgs84.geometry
df_bounds_exact = to_file(df_bounds_exact, "df_bounds_exact")

df_explode = to_file(df_bounds_exact.explode(index_parts=False), "df_explode")

df_simplify = to_file(simplify(df_explode, 1), "df_simplify")

df_buffer = to_file(buffer(df_simplify, 100), "df_buffer")

df_hull = to_file(convex_hull(df_buffer), "df_hull")

df_hull_dissolve = to_file(dissolve(df_hull), "df_hull_dissolve")

df_hull_fill = to_file(fill(df_hull_dissolve), "df_hull_fill")

df_hull_fill_simplify = to_file(simplify(df_hull_fill, 100), "df_hull_fill_simplify")

bounds = to_file(df_hull_fill_simplify, 'bounds')

bounds.reset_index()[['ID', 'EN', 'FR', 'PRIORITY', 'DURATION', 'geometry']].set_index(['ID']).to_file('bounds.geojson')
