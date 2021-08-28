# import libraries
import urllib.request as urllib2
from bs4 import BeautifulSoup
import pandas as pd
import os
import datetime
import sys
sys.path.append('../util')
import common
import firestarr
import timeit
import logging
import shutil
import sys
sys.path.append(os.path.dirname(sys.executable))
sys.path.append('/usr/local/bin')
import gdal_merge as gm

SITE = 'http://psaasbc.dss.intellifirenwt.com'
URL = SITE + '/jobs/archive/'
DIR = '/FireGUARD/data/fgmj/'
EXT_DIR = os.path.abspath(os.path.join(DIR, '../extracted/fgmj'))
common.ensure_dir(EXT_DIR)
CREATION_OPTIONS = ['COMPRESS=LZW', 'TILED=YES']

def getPage(url):
    # query the website and return the html to the variable 'page'
    page = urllib2.urlopen(url)
    # parse the html using beautiful soup and return
    return BeautifulSoup(page, 'html.parser')

p = getPage(URL)
a = p.findAll('a')
zips = [x.get('href') for x in a if x.get('href').endswith('.zip')]
fires = sorted(set([x[x.rindex('/') + 1:x.index('_')] for x in zips]))

times = {}
recent = {}
simtimes = {}
totaltime = 0
for f in fires:
    print(f)
    times[f] = [datetime.datetime.strptime(x[x.rindex('_') + 1:x.rindex('.')], '%Y%m%d%H%M%S%f') for x in zips if x[x.rindex('/') + 1:x.index('_')] == f]
    recent[f] = {
                    'time': max(times[f]),
                    'url': [x for x in zips if x[x.rindex('/') + 1:x.index('_')] == f and datetime.datetime.strptime(x[x.rindex('_') + 1:x.rindex('.')], '%Y%m%d%H%M%S%f') == max(times[f])][0],
                }
    z = common.save_http(DIR, SITE + recent[f]['url'], ignore_existing=True)
    cur_dir = os.path.join(EXT_DIR, os.path.basename(z)[:-4])
    common.unzip(z, cur_dir)
    fgmj = os.path.join(cur_dir, 'job.fgmj')
    if os.path.exists(fgmj):
        t0 = timeit.default_timer()
        log_name = firestarr.do_run(fgmj)
        t1 = timeit.default_timer()
        if log_name is not None:
            simtimes[f] = t1 - t0
            totaltime = totaltime + simtimes[f]
            logging.info("Took {}s to run {}".format(simtimes[f], f))

import gdal_retile as gr
import gdal_calc
import gdal

def merge_dir(dir_input):
    # HACK: for some reason output tiles were both being called 'probability'
    import importlib
    importlib.reload(gr)
    TILE_SIZE = str(1024)
    file_tmp = dir_input + '_tmp.tif'
    file_out = dir_input + '.tif'
    file_int = dir_input + '_int.tif'
    co = list(itertools.chain.from_iterable(map(lambda x: ['-co', x], CREATION_OPTIONS)))
    files = [os.path.join(dir_input, x) for x in sorted(os.listdir(dir_input)) if x.endswith('.tif')]
    gm.main(['', '-n', '0', '-a_nodata', '0'] + co + ['-o', file_tmp] + files)
    #gm.main(['', '-n', '0', '-a_nodata', '0', '-co', 'COMPRESS=DEFLATE', '-co', 'ZLEVEL=9', '-co', 'TILED=YES', '-o', file_tmp] + files)
    shutil.move(file_tmp, file_out)
    gdal_calc.Calc(A=file_out, outfile=file_tmp, calc='A*100', NoDataValue=0, type='Byte', creation_options=CREATION_OPTIONS)
    shutil.move(file_tmp, file_int)
    dir_tile = os.path.join(dir_input, 'tiled')
    if os.path.exists(dir_tile):
        print('Removing {}'.format(dir_tile))
        shutil.rmtree(dir_tile)
    dir_tile = common.ensure_dir(dir_tile)
    gr.main(['', '-ot', 'Byte'] + co + ['-v', '-ps', TILE_SIZE, TILE_SIZE, '-overlap', '0', '-targetDir', dir_tile, file_int])
    tiles = [os.path.join(dir_tile, x) for x in sorted(os.listdir(dir_tile)) if x.endswith('.tif')]
    for t in tiles:
        # print('Checking {}'.format(t))
        ds = gdal.Open(t, 1)
        rb = ds.GetRasterBand(1)
        vals = rb.ReadAsArray(0, 0)
        if (vals == 0).all():
            print("Removing empty tile {}".format(t))
            os.remove(t)
        vals = None
        rb = None
        ds = None

n = len(simtimes)
if n > 0:
    logging.info("Total of {} fires took {}s - average time is {}s".format(n, totaltime, totaltime / n))
    merge_dir('/FireGUARD/data/output/probability')
    merge_dir('/FireGUARD/data/output/perimeter')

import os
from bs4 import BeautifulSoup
import numpy as np
import gdal
b = BeautifulSoup("".join([line.rstrip('\n') for line in open('/FireGUARD/FireSTARR/probability_int.qml')]))
palette = b.findAll('paletteentry')
p = {}
for e in palette:
    h = e.get('color')[1:]
    # rgb = list(int(h[i:i+2], 16) for i in (0, 2, 4)) + [int(e.get('alpha'))]
    rgb = list(int(h[i:i+2], 16) for i in (0, 2, 4)) + [min(255, int(255 * int(e.get('value'))/ 100.0) + 30)]
    p[int(e.get('value'))] = rgb

file_int = '/FireGUARD/data/output/probability_int.tif'
file_rgba = '/FireGUARD/data/output/probability_rgb.tif'
if os.path.exists(file_rgba):
    os.remove(file_rgba)

DRIVER_TIF = gdal.GetDriverByName('GTiff')
ds = gdal.Open(file_int, 1)

tmp_ds = gdal.GetDriverByName('MEM').CreateCopy('', ds, 0)
tmp_ds.AddBand()
tmp_ds.AddBand()
tmp_ds.AddBand()

dst_ds = DRIVER_TIF.CreateCopy(file_rgba, tmp_ds, 0, options=CREATION_OPTIONS)
dst_ds = None
tmp_ds = None
rb = ds.GetRasterBand(1)
vals = rb.ReadAsArray(0, 0)
u = np.unique(vals)
for i in u:
    if not i in p.keys():
        print('Setting {} to be transparent'.format(i))
        p[i] = [0, 0, 0, 0]

rb = None
ds = None

# get_r = np.vectorize(lambda v: p[v][0])
# get_r = np.frompyfunc(lambda v: p[v][0], 1, 1)
# r = get_r(vals)


get_rgb = np.frompyfunc(lambda v: p[v], 1, 1)
v_rgb = get_rgb(vals)

get_r = np.vectorize(lambda v: v[0])
get_g = np.vectorize(lambda v: v[1])
get_b = np.vectorize(lambda v: v[2])
get_a = np.vectorize(lambda v: v[3])

r = get_r(v_rgb)
g = get_g(v_rgb)
b = get_b(v_rgb)
a = get_a(v_rgb)

ds = gdal.Open(file_rgba, 1)
def write_band(i, v):
    rb = ds.GetRasterBand(i)
    rb.WriteArray(v, 0, 0)
    rb.FlushCache()
    rb = None

write_band(1, r)
write_band(2, g)
write_band(3, b)
write_band(4, a)
ds = None
