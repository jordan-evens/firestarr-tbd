import datetime
import math
import os

import geopandas as gpd
import gis
import model_data
import numpy as np
import pandas as pd
import pyproj
from common import (
    CRS_LAMBERT_STATSCAN,
    CRS_SIMINPUT,
    DEFAULT_GROUP_DISTANCE_KM,
    DEFAULT_M3_LAST_ACTIVE_IN_DAYS,
    KM_TO_M,
    USE_CWFIS,
    YEAR,
    logging,
)
from tqdm import tqdm


def get_fires_active(dir_out, status_include=None, status_omit=["OUT"]):
    str_year = str(YEAR)

    def fix_name(name):
        if isinstance(name, str) or not (name is None or np.isnan(name)):
            s = str(name).replace("-", "_")
            if s.startswith(str_year):
                s = s[len(str_year) :]
            if s.endswith(str_year):
                s = s[: -len(str_year)]
            s = s.strip("_")
            return s
        return ""

    # this isn't an option, because it filters out fires
    # df_dip = model_data.get_fires_dip(dir_out, status_ignore=None)
    try:
        df_ciffc, ciffc_json = model_data.get_fires_ciffc(dir_out, status_ignore=None)
        df_ciffc["fire_name"] = df_ciffc["field_agency_fire_id"].apply(fix_name)
    except KeyboardInterrupt as ex:
        raise ex
    except Exception:
        df_ciffc, ciffc_json = model_data.get_fires_dip(
            dir_out, status_ignore=None, year=YEAR
        )
        df_ciffc["fire_name"] = df_ciffc["firename"].apply(fix_name)
        df_ciffc = df_ciffc.rename(
            columns={
                "stage_of_control": "field_stage_of_control_status",
                "firename": "field_agency_fire_id",
                "hectares": "field_fire_size",
            }
        )
    if DEFAULT_M3_LAST_ACTIVE_IN_DAYS:
        last_active_since = datetime.date.today() - datetime.timedelta(
            days=DEFAULT_M3_LAST_ACTIVE_IN_DAYS
        )
    else:
        last_active_since = None
    if USE_CWFIS:
        df_m3, m3_json = model_data.get_fires_m3(dir_out, last_active_since)
    else:
        df_m3 = model_data.get_m3_download(dir_out, df_ciffc, last_active_since)
    df_m3["guess_id"] = df_m3["guess_id"].apply(fix_name)
    df_m3["fire_name"] = df_m3.apply(
        lambda x: fix_name(x["guess_id"] or x["id"]), axis=1
    )
    df_ciffc_non_geo = df_ciffc.loc[:]
    del df_ciffc_non_geo["id"]
    del df_ciffc_non_geo["geometry"]
    df_matched = pd.merge(
        df_m3, df_ciffc_non_geo, left_on="fire_name", right_on="fire_name"
    )
    # fires that were matched but don't join with ciffc
    missing = [
        x for x in list(set(np.unique(df_m3.guess_id)) - set(df_matched.fire_name)) if x
    ]
    if 0 < len(missing):
        logging.error(
            "M3 guessed polygons for %d fires that aren't listed on ciffc: %s",
            len(missing),
            str(missing),
        )
    # Only want to run matched polygons, and everything else plus ciffc points
    id_matched = df_matched.id
    id_m3 = df_m3.id
    id_diff = list(set(id_m3) - set(id_matched))
    df_matched = df_matched.set_index(["id"])
    df_unmatched = df_m3.set_index(["id"]).loc[id_diff]
    logging.info("M3 has %d polygons that are not tied to a fire", len(df_unmatched))
    if status_include:
        df_matched = df_matched[
            df_matched.field_stage_of_control_status.isin(status_include)
        ]
        logging.info(
            "M3 has %d polygons that are tied to %s fires",
            len(df_matched),
            status_include,
        )
    if status_omit:
        df_matched = df_matched[
            ~df_matched.field_stage_of_control_status.isin(status_omit)
        ]
        logging.info(
            "M3 has %d polygons that aren't tied to %s fires",
            len(df_matched),
            status_omit,
        )
    df_poly_m3 = pd.concat([df_matched, df_unmatched])
    logging.info("Using %d polygons as inputs", len(df_poly_m3))
    # now find any fires that weren't matched to a polygon
    diff_ciffc = list((set(df_ciffc.fire_name) - set(df_matched.fire_name)))
    df_ciffc_pts = df_ciffc.set_index(["fire_name"]).loc[diff_ciffc]
    if status_include:
        df_ciffc_pts = df_ciffc_pts[
            df_ciffc_pts.field_stage_of_control_status.isin(status_include)
        ]
    if status_omit:
        df_ciffc_pts = df_ciffc_pts[
            ~df_ciffc_pts.field_stage_of_control_status.isin(status_omit)
        ]
    logging.info("Found %d fires that aren't matched with polygons", len(df_ciffc_pts))
    df_poly = df_poly_m3.reset_index()[["fire_name", "geometry"]]

    def area_to_radius(a):
        return math.sqrt(a / math.pi)

    df_ciffc_pts = df_ciffc_pts.to_crs(df_poly.crs)
    # HACK: put in circles of proper area if no perimeter
    df_ciffc_pts["radius"] = df_ciffc_pts["field_fire_size"].apply(
        lambda x: max(0.1, area_to_radius(max(0, x)))
    )
    df_ciffc_pts["geometry"] = df_ciffc_pts.apply(
        lambda x: x.geometry.buffer(x.radius), axis=1
    )
    df_pts = df_ciffc_pts.reset_index()[["fire_name", "geometry"]]
    df_fires = pd.concat([df_pts, df_poly])
    return df_fires


def separate_points(f):
    pts = [x for x in f if x.geom_type == "Point"]
    polys = [x for x in f if x.geom_type != "Point"]
    return pts, polys


def group_fires(df_fires, group_distance_km=DEFAULT_GROUP_DISTANCE_KM):
    group_distance = group_distance_km * KM_TO_M
    crs = df_fires.crs

    def to_gdf(d):
        return gpd.GeoDataFrame(geometry=d, crs=crs)

    groups = to_gdf(df_fires["geometry"])
    pts, polys = separate_points(groups.geometry)
    df_polys = to_gdf(polys)
    # we can check if any points are within polygons, and throw out any that are
    pts_keep = [p for p in pts if not np.any(df_polys.contains(p))]
    # p_check = [to_gdf([x]) for x in (pts_keep + polys)]
    p_check = to_gdf(pts_keep + polys)
    p = p_check.iloc[:1]
    p_check = p_check.iloc[1:]
    # just check polygon proximity to start
    # logging.info("Grouping polygons")
    with tqdm(desc="Grouping fires", total=len(p_check)) as tq:
        p_done = []
        while 0 < len(p_check):
            n_prev = len(p_check)
            compare_to = to_gdf(p_check.geometry)
            # distances should be in meters
            compare_to["dist"] = compare_to.apply(
                lambda x: min(x["geometry"].distance(y) for y in p.geometry), axis=1
            )
            p_nearby = compare_to[compare_to.dist <= group_distance]
            if 0 < len(p_nearby):
                group = list(p.geometry) + list(p_nearby.geometry)
                g_pts, g_polys = separate_points(group)
                g_dissolve = list(to_gdf(g_polys).dissolve().geometry)
                p = to_gdf(g_pts + g_dissolve)
                # need to check whatever was far away
                p_check = compare_to[compare_to.dist > group_distance][["geometry"]]
            else:
                # nothing close to this, so done with it
                p_done.append(p)
                p = p_check.iloc[:1]
                p_check = p_check.iloc[1:]
            tq.update(n_prev - len(p_check))
    tq.update(1)
    merged = [p] + p_done
    # NOTE: year should not be relevant, because we just care about the
    # projection, not the data
    zone_rasters = gis.find_raster_meridians(YEAR)
    zone_rasters = {k: v for k, v in zone_rasters.items() if not v.endswith("_5.tif")}

    def find_best_zone_raster(lon):
        best = 9999
        for i in zone_rasters.keys():
            if abs(best - lon) > abs(i - lon):
                best = i
        return zone_rasters[best]

    for i in tqdm(range(len(merged)), desc="Naming groups"):
        df_group = merged[i]
        # HACK: can't just convert to lat/long crs and use centroids from that
        # because it causes a warning
        df_dissolve = df_group.dissolve()
        centroid = df_dissolve.centroid.to_crs(CRS_SIMINPUT).iloc[0]
        df_group["lon"] = centroid.x
        df_group["lat"] = centroid.y
        # # df_fires = df_fires.to_crs(CRS)
        # df_fires = df_fires.sort_values(['area_calc'])
        # HACK: name based on UTM coordinates
        r = find_best_zone_raster(centroid.x)
        zone_wkt = gis.GetSpatialReference(r).ExportToWkt()
        zone = int(os.path.basename(r).split("_")[1])
        # HACK: just use gpd since it's easier
        centroid_utm = (
            gpd.GeoDataFrame(geometry=[centroid], crs=CRS_SIMINPUT)
            .to_crs(zone_wkt)
            .iloc[0]
            .geometry
        )
        # this is too hard to follow
        # df_group['fire_name'] = f"{zone}N_{int(centroid_utm.x)}_{int(centroid_utm.y)}"
        BM_MULT = 10000
        easting = int((centroid_utm.x) // BM_MULT)
        northing = int((centroid_utm.y) // BM_MULT)
        basemap = easting * 1000 + northing
        # df_group['utm_zone'] = zone
        # df_group['basemap'] = int(f"{easting:02d}{northing:03d}")
        n_or_s = "N" if centroid.y >= 0 else "S"
        df_group["fire_name"] = f"{zone}{n_or_s}_{basemap}"
        # it should be impossible for 2 groups to be in the same basemap
        # because they are grouped within > 10km
        merged[i] = df_group
    results = pd.concat(merged)
    logging.info("Created %d groups", len(results))
    return results


def get_fires_folder(dir_fires, crs=CRS_LAMBERT_STATSCAN):
    proj = pyproj.CRS(crs)
    df_fires = None
    for root, dirs, files in os.walk(dir_fires):
        for f in [x for x in files if x.lower().endswith(".shp")]:
            file_shp = os.path.join(root, f)
            df_fire = gpd.read_file(file_shp).to_crs(proj)
            df_fires = pd.concat([df_fires, df_fire])
    df_fires["fire_name"] = df_fires["FIRENUMB"]
    return df_fires
