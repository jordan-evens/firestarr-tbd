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


# WFS_ROOT = 'https://cwfis.cfs.nrcan.gc.ca/service/data/fireops/wms?service=wfs&version=2.0.0'
# WFS_ROOT = 'http://s-edm-sahal:8080/geoserver/ows?service=wfs&version=2.0.0'
WFS_ROOT = 'http://s-edm-sahal.nrn.nrcan.gc.ca:8080/geoserver/ows?service=wfs&version=2.0.0'
WFS_CIFFC = 'https://geoserver.ciffc.net/geoserver/wfs?version=2.0.0'
EPSG = 3978
DEFAULT_STATUS_IGNORE = ["OUT", "UC", "BH", "U"]
# DEFAULT_STATUS_KEEP = ["OC"]

# def query_geoserver(table_name, f_out, features=None,filter=None):
#     while True:
#         try:
#             #https://cwfis.cfs.nrcan.gc.ca/service/data/fireops/wms?service=wfs&version=2.0.0&request=GetFeature&typenames=fireops:cwfis_allstn2022&outputFormat=application/json
#             logging.debug(f'Getting table {table_name} in projection {str(EPSG)}')
#             request_url = 'https://cwfis.cfs.nrcan.gc.ca/service/data/fireops/wms'
#             request_url += "?service=wfs&request=GetFeature&version=2.0.0"
#             request_url += "&typeName=%s" % (table_name)
#             request_url += "&srsName=EPSG:%s" % (EPSG)
#             if features != None:
#                 request_url += "&propertyName=%s" % (features)
#             if filter != None:
#                 request_url += "&CQL_FILTER=%s" % (filter)
#             request_url += "&outputFormat=application/json"
#             f_out = get_input(request_url, f_out)
#             return f_out
#         except ConnectionResetError as e:
#             print(e)
#             t = 5
#             print(f'Retrying in {t} seconds')
#             time.sleep(t)


def query_geoserver(table_name, f_out, features=None, filter=None, wfs_root=WFS_ROOT):
    logging.debug(f'Getting table {table_name} in projection {str(EPSG)}')
    #https://cwfis.cfs.nrcan.gc.ca/service/data/fireops/wms?service=wfs&version=2.0.0&request=GetFeature&typenames=fireops:cwfis_allstn2022&outputFormat=application/json
    # request_url = f'https://cwfis.cfs.nrcan.gc.ca/service/data/fireops/wms?service=wfs&version=2.0.0&request=GetFeature&typename={table_name}&outputFormat=application/json&srsName=EPSG:{str(EPSG)}'
    request_url = f'{wfs_root}&request=GetFeature&typename={table_name}&outputFormat=application/json'
    if features is not None:
        request_url += f'&propertyName={features}'
    if filter is not None:
        # request_url += f'&CQL_FILTER={filter}'
        request_url += f'&CQL_FILTER={urllib.parse.quote(filter)}'
    logging.debug(request_url)
    print(request_url)
    return try_save(lambda _: save_http(_,
                                        save_as=f_out,
                                        check_modified=False,
                                        ignore_existing=False),
                    request_url)


def get_fires_m3(dir_out):
    f_out = f'{dir_out}/m3_polygons_current.json'
    features='uid,geometry,hcount,mindate,maxdate,firstdate,lastdate,area,fcount,status,firetype,guess_id,consis_id'
    table_name = 'public:m3_polygons_current'
    # NOTE: no need to filter since current?
    # today = datetime.datetime.now().strftime('%Y%m%d')
    # yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime('%Y%m%d')
    # filter = f'"maxdate">=\'{today}\''
    filter = None
    f_json = query_geoserver(table_name, f_out, features=features, filter=filter)
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
                              "current=true",
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
    layer = 'public:firewx_stns_current'
    # layer = 'public:firewx_stns_{:04d}'
    # URL = "https://cwfis.cfs.nrcan.gc.ca/geoserver/wfs?service=WFS&request=GetFeature&typeNames=public:firewx_stns_{:04d}&cql_filter=rep_date=={:04d}-{:02d}-{:02d}T12:00:00&outputFormat=csv"
    df = pd.DataFrame()
    for date in dates:
        year = date.year
        month = date.month
        day = date.day
        url = WFS_ROOT + f'&request=GetFeature&typeNames={layer}&cql_filter=rep_date=={year:04d}-{month:02d}-{day:02d}T12:00:00&outputFormat=csv'
        file_out = os.path.join(dir_out, "{:04d}-{:02d}-{:02d}.csv".format(year, month, day))
        if not os.path.exists(file_out):
            save_http(url, file_out)
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
    url = f'http://spotwx.io/api.php?key={SPOTWX_KEY}&model={model}&lat={round(lat, 3)}&lon={round(long, 3)}&ens_val=members'
    # url = f'https://spotwx.io/api.php?key={SPOTWX_KEY}&model={model}&lat={round(lat, 3)}&lon={round(long, 3)}&ens_val=members'
    content = None
    try:
        content = try_save(get_http, url)
        content = str(content, encoding='utf-8')
    except KeyboardInterrupt as e:
        raise e
    except Exception as e:
        # so retried but never got content, so url is not reachable at all
        logging.fatal("Could not get wx from %s", url)
        raise e
    # have content, but now we need to see if we can parse it
    try:
        df_initial = pd.read_csv(io.StringIO(content))
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
    except KeyboardInterrupt as ex:
        raise ex
    except Exception:
        # so we couldn't parse the content, but we have something
        # logging.fatal("Could not parse content for %s", url)
        raise ParseError(content)


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
