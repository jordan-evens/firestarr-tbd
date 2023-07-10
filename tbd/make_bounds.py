import sys
sys.path.append('../util')
from common import *
import geopandas as gpd

DIR = ensure_dir('../data/tmp/bounds')
CRS = 'WGS84'
KM_TO_M = 1000

def to_file(df, name):
    print(name)
    df.to_file(os.path.join(DIR, f"{name}.geojson"))
    df.to_file(os.path.join(DIR, f"{name}.shp"))
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
    df.simplify(tolerance=km * KM_TO_M)
    return df.to_crs(CRS)

def convex_hull(df):
    df = df.to_crs(CRS_ORIG)
    df.geometry = df.convex_hull
    return df.to_crs(CRS)

df_bounds = to_file(gpd.read_file('bounds.geojson').sort_values(['EN']), "df_bounds")

df_canada = gpd.read_file('../data/tmp/canada/lpr_000b16a_e.shp').sort_values(['PRENAME'])
CRS_ORIG = df_canada.crs
df_canada_wgs84 = df_canada.to_crs(CRS)
df_bounds_exact = df_bounds.iloc[:]
df_bounds_exact.geometry = df_canada.geometry
to_file(df_bounds_exact, "df_bounds_exact")

df_explode = to_file(df_bounds_exact.explode(index_parts=False), "df_explode")

df_envelope = to_file(to_envelope(df_explode), "df_envelope")

df_envelope_dissolve = to_file(df_envelope.dissolve(by='ID'), "df_envelope_dissolve")

df_buffer = to_file(buffer(df_envelope, 100), "df_buffer")

df_buffer_dissolve = to_file(df_buffer.dissolve(by='ID'), "df_buffer_dissolve")

df_buffer_envelope = to_file(to_envelope(df_buffer), "df_buffer_envelope")

df_buffer_envelope_dissolve = to_file(dissolve(df_buffer_envelope), "df_buffer_envelope_dissolve")

df_buffer_envelop_dissolve_simplify = to_file(simplify(df_buffer_envelope_dissolve, 10), "df_buffer_envelop_dissolve_simplify")

df_buffer_envelope_buffer = to_file(buffer(df_buffer_envelope, 10), "df_buffer_envelope_buffer")

df_buffer_envelope_buffer_envelope = to_file(to_envelope(df_buffer_envelope_buffer), "df_buffer_envelope_buffer_envelope")

df_buffer_envelope_buffer_envelope_dissolve = to_file(dissolve(df_buffer_envelope_buffer_envelope), "df_buffer_envelope_buffer_envelope_dissolve")

df_buffer_envelope_buffer_envelope_simplify = to_file(simplify(df_buffer_envelope_buffer_envelope, 10), "df_buffer_envelope_buffer_envelope_simplify")

df_buffer_envelope_buffer_envelope_simplify = to_file(simplify(df_buffer_envelope_buffer_envelope, 10), "df_buffer_envelope_buffer_envelope_simplify")

df_buffer_envelope_buffer_envelope_simplify_dissolve = to_file(dissolve(df_buffer_envelope_buffer_envelope_simplify), "df_buffer_envelope_buffer_envelope_simplify_dissolve")

df_hull = to_file(convex_hull(df_buffer_envelope_buffer_envelope_simplify_dissolve), "df_hull")

df_hull_direct = to_file(convex_hull(df_envelope_dissolve), "df_hull_direct")

df_hull_buffer = to_file(convex_hull(df_buffer_dissolve), "df_hull_buffer")

df_hull_buffer_envelope = to_file(convex_hull(df_buffer_envelope_buffer_envelope_dissolve), "df_hull_buffer_envelope")

df_hull_buffer_envelope.reset_index()[['ID', 'EN', 'FR', 'PRIORITY', 'DURATION', 'geometry']].set_index(['ID']).to_file('bounds.geojson')
