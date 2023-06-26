from common import *
import logging
import io
import urllib
import pandas as pd
import requests
import os
import datetime
import json
import numpy as np
import geopandas as gpd

from osgeo import gdal

# still getting messages that look like they're from gdal when debug is on, but
# maybe they're from a package that's using it?
gdal.UseExceptions()
gdal.SetConfigOption('CPL_LOG', '/dev/null')
gdal.SetConfigOption('CPL_DEBUG', 'OFF')
gdal.SetErrorHandler('CPLLoggingErrorHandler')

WFS_ROOT = 'https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wms?service=wfs&version=2.0.0'
WFS_CIFFC = 'https://geoserver.ciffc.net/geoserver/wfs?version=2.0.0'
EPSG = 3978
DEFAULT_STATUS_IGNORE = ["OUT", "UC", "BH", "U"]
# DEFAULT_STATUS_KEEP = ["OC"]

def query_geoserver(table_name, f_out, features=None, filter=None, wfs_root=WFS_ROOT):
    logging.debug(f'Getting table {table_name} in projection {str(EPSG)}')
    request_url = f'{wfs_root}&request=GetFeature&typename={table_name}&outputFormat=application/json'
    if features is not None:
        request_url += f'&propertyName={features}'
    if filter is not None:
        request_url += f'&CQL_FILTER={urllib.parse.quote(filter)}'
    logging.debug(request_url)
    print(request_url)
    return try_save(lambda _: save_http(_,
                                        save_as=f_out,
                                        check_modified=False,
                                        ignore_existing=False),
                    request_url)


def get_fires_m3(dir_out, for_day=datetime.date.today()):
    f_out = f'{dir_out}/m3_polygons.json'
    # features='uid,geometry,hcount,mindate,maxdate,firstdate,lastdate,area,fcount,status,firetype,guess_id,consis_id'
    features = 'uid,geometry,hcount,firstdate,lastdate,area,guess_id'
    table_name = 'public:m3_polygons'
    # NOTE: no need to filter since current?
    # today = datetime.datetime.now().strftime('%Y%m%d')
    # yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y%m%d')
    # filter = f'"maxdate">=\'{today}\''
    # filter = None
    filter = f"lastdate during {for_day.strftime('%Y-%m-%d')}T00:00:00Z/P1D"
    f_json = query_geoserver(table_name, f_out, features=features, filter=filter)
    logging.debug(f"Reading {f_json}")
    gdf = gpd.read_file(f_json)
    return gdf, f_json
    # fires_shp = f_out.replace('.json', '.shp')
    # gdf.to_file(fires_shp)
    # return gdf, fires_shp


# def get_fires_dip(dir_out, status_keep=DEFAULT_STATUS_KEEP):
def get_fires_dip(dir_out, status_ignore=DEFAULT_STATUS_IGNORE, year=datetime.date.today().year):
    f_out = f'{dir_out}/dip_current.json'
    table_name = "public:activefires"
    # features = "*"
    features = None
    # filter = None
    if status_ignore is None:
        status_ignore = []
    filter = " and ".join([f'"stage_of_control"<>\'{status}\'' for status in status_ignore]
                          + [
                            #   "current=true",
                              "agency<>'ak'",
                              "agency<>'conus'",
                              f"startdate during {year}-01-01T00:00:00Z/P1Y"
                             ])
    # filter = " or ".join([f'"stage_of_control"=\'{status}\'' for status in status_keep]) or None
    f_json = query_geoserver(table_name, f_out, features=features, filter=filter)
    gdf = gpd.read_file(f_json)
    return gdf, f_json


# def get_fires_ciffc(dir_out, status_keep=DEFAULT_STATUS_KEEP):
def get_fires_ciffc(dir_out, status_ignore=DEFAULT_STATUS_IGNORE):
    table_name = "ciffc:ytd_fires"
    f_out = f'{dir_out}/ciffc_current.json'
    # features = "*"
    features = None
    # filter = None
    if status_ignore is None:
        status_ignore = []
    filter = " and ".join([f'"stage_of_control"<>\'{status}\'' for status in status_ignore]) or None
    # filter = " or ".join([f'"stage_of_control"=\'{status}\'' for status in status_keep]) or None
    f_json = query_geoserver(table_name, f_out, features=features, filter=filter, wfs_root=WFS_CIFFC)
    gdf = gpd.read_file(f_json)
    return gdf, f_json


def get_wx_cwfis(dir_out, dates):
    # layer = 'public:firewx_stns_current'
    # HACK: use 2022 because it has 2023 in it right now
    layer = 'public:firewx_stns_2022'
    df = pd.DataFrame()
    for date in dates:
        year = date.year
        month = date.month
        day = date.day
        url = WFS_ROOT + f'&request=GetFeature&typeNames={layer}&cql_filter=rep_date=={year:04d}-{month:02d}-{day:02d}T12:00:00&outputFormat=csv'
        print(url)
        file_out = os.path.join(dir_out, "{:04d}-{:02d}-{:02d}.csv".format(year, month, day))
        if not os.path.exists(file_out):
            file_out = try_save(lambda _: save_http(_, file_out), url)
        logging.debug("Reading {}".format(file_out))
        df_day = pd.read_csv(file_out)
        df = pd.concat([df, df_day])
    df = df[['wmo', 'lat', 'lon', 'prov', 'rep_date', 'temp', 'rh', 'ws', 'precip', 'ffmc', 'dmc', 'dc', 'isi', 'bui', 'fwi']]
    df['date'] = df.apply(lambda x: datetime.datetime.strptime(x['rep_date'], '%Y-%m-%dT%H:00:00'), axis=1)
    df['year'] = df.apply(lambda x: x['date'].year, axis=1)
    df['month'] = df.apply(lambda x: "{:02d}".format(x['date'].month), axis=1)
    df['day'] = df.apply(lambda x: "{:02d}".format(x['date'].day), axis=1)
    df = df[['wmo', 'lat', 'lon', 'prov', 'year', 'month', 'day', 'temp', 'rh', 'ws', 'precip', 'ffmc', 'dmc', 'dc', 'isi', 'bui', 'fwi']]
    df = df.sort_values(['year', 'month', 'day', 'wmo'])
    crs = 'WGS84'
    # is there any reason to make actual geometry?
    gdf = gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df['lon'], df['lat']), crs=crs)
    return gdf


def get_spotwx_key():
    try:
        key = CONFIG.get('keys', 'spotwx')
    except configparser.NoSectionError:
        key = None
    if key is None or 0 == len(key):
        raise RuntimeError('spotwx api key is required')
    # get rid of any quotes that might be in settings file
    key = key.replace('"', '').replace("'", '')
    return key


def get_wx_spotwx(lat, long):
    SPOTWX_KEY =  get_spotwx_key()
    metmodel = "gem_reg_10km" if lat > 67 else "gem_lam_continental"
    # HACK: can't figure out a way to just get a csv directly, so parsing html javascript array for data
    url = f'https://spotwx.com/products/grib_index.php?key={SPOTWX_KEY}&model={metmodel}&lat={round(lat, 3)}&lon={round(long, 3)}&display=table_prometheus'
    response = requests.get(url, verify=False, headers=HEADERS)
    content = str(response.content, encoding='utf-8')
    start_pos = content.find("aDataSet = [\n")
    data = content[start_pos+12:]
    end_pos = data.find("];")
    data = data[0:end_pos]
    data = data.strip()
    d = json.loads('[' + data.replace("'", '"') + ']')
    wx = [[datetime.datetime.strptime(f'{h[0]}{int(h[1]):02d}', '%d/%m/%Y%H')] + [float(v) for v in h[2:]] for h in d]
    cols = ["datetime", "temp", "rh", "wd", "ws", "precip"]
    df_spotwx = pd.DataFrame(data=wx, columns=cols)
    df_spotwx['lat'] = lat
    df_spotwx['long'] = long
    df_spotwx['source'] = f'spotwx_{metmodel}'
    return df_spotwx


def get_wx_ensembles(lat, long):
    SPOTWX_KEY =  get_spotwx_key()
    model = "geps"
    url = f'https://spotwx.io/api.php?key={SPOTWX_KEY}&model={model}&lat={round(lat, 3)}&lon={round(long, 3)}&ens_val=members'
    print(url)
    # url = f'https://spotwx.io/api.php?key={SPOTWX_KEY}&model={model}&lat={round(lat, 3)}&lon={round(long, 3)}&ens_val=members'
    content = None
    def get_initial(url):
        content = get_http(url)
        content = str(content, encoding='utf-8')
        df_initial = pd.read_csv(io.StringIO(content))
        if "UTC_OFFSET" not in df_initial.columns:
            raise ParseError(content)
        return df_initial
    # HACK: wrap initial parse with this so it retries if we get a page that isn't what we want back
    df_initial = try_save(get_initial, url)
    if list(np.unique(df_initial.UTC_OFFSET)) != [0]:
        raise RuntimeError("Expected weather in UTC time")
    index = ['MODEL', 'LAT', 'LON', 'ISSUEDATE', 'UTC_OFFSET', 'DATETIME']
    all_cols =  np.unique([x[:x.index('_')] for x in df_initial.columns if '_' in x])
    cols = ['TMP', 'RH', 'WSPD', 'WDIR', 'PRECIP']
    keep_cols = [x for x in df_initial.columns if x in index or np.any([x.startswith(f'{_}_') for _ in cols])]
    df_by_var = pd.melt(df_initial, id_vars=index, value_vars=keep_cols)
    df_by_var['var'] = df_by_var['variable'].apply(lambda x: x[:x.rindex('_')])
    df_by_var['id'] = [0 if 'CONTROL' == id else int(id) for id in df_by_var['variable'].apply(lambda x: x[x.rindex('_') + 1:])]
    del df_by_var['variable']
    df_wx = pd.pivot(df_by_var, index=index + ['id'], columns='var', values='value').reset_index()
    df_wx.groupby(['id'])['PRECIP_ttl']
    df = None
    for i, g in df_wx.groupby(['id']):
        g['PRECIP'] = (g['PRECIP_ttl'] - g['PRECIP_ttl'].shift(1)).fillna(0)
        df = pd.concat([df, g])
    # HACK: for some reason rain is less in subsequent hours sometimes, so make sure nothing is negative
    df.loc[df['PRECIP'] < 0, 'PRECIP'] = 0
    del df['PRECIP_ttl']
    df = df.reset_index()
    del df['index']
    df.columns.name = ''
    # make sure we're in UTC and use that for now
    assert [0] == np.unique(df['UTC_OFFSET'])
    df.columns = [x.lower() for x in df.columns]
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.rename(columns={'lon': 'long', 'tmp': 'temp',
                            'wdir': 'wd',
                            'wspd': 'ws'})
    df['issuedate'] = pd.to_datetime(df['issuedate'])
    index_final = ['model', 'lat', 'long', 'issuedate', 'id']
    df = df[index_final + ['datetime', 'temp', 'rh', 'wd', 'ws', 'precip']]
    df = df.set_index(index_final)
    return df


def wx_interpolate(df):
    date_min = df['datetime'].min()
    date_max = df['datetime'].max()
    times = pd.DataFrame(pd.date_range(date_min, date_max, freq="H").values, columns=['datetime'])
    index_names = df.index.names
    groups = []
    for i, g in df.groupby(index_names):
        g_fill = pd.merge(times, g, how='left')
        # treat rain as if it all happened at start of any gaps
        g_fill['precip'] = g_fill['precip'].fillna(0)
        g_fill = g_fill.fillna(method='ffill')
        g_fill[index_names] = i
        groups.append(g_fill)
    df_filled = pd.concat(groups)
    df_filled.set_index(index_names)
    return df_filled
