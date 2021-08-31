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
import shlex
import sys
sys.path.append(os.path.dirname(sys.executable))
sys.path.append('/usr/local/bin')
import gdal_merge as gm
import itertools

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

def run_fires():
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
            try:
                t0 = timeit.default_timer()
                log_name = firestarr.do_run(fgmj)
                t1 = timeit.default_timer()
                if log_name is not None:
                    simtimes[f] = t1 - t0
                    totaltime = totaltime + simtimes[f]
                    logging.info("Took {}s to run {}".format(simtimes[f], f))
            except Exception as e:
                logging.error(e)
    return simtimes, totaltime

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
    import subprocess
    file_cr = dir_input + '_cr.tif'
    subprocess.call('gdaldem color-relief {} /FireGUARD/FireSTARR/col.txt {} -alpha -co COMPRESS=LZW -co TILED=YES'.format(file_int, file_cr), shell=True)
    dir_tile = common.ensure_dir(dir_tile)
    subprocess.run('python /usr/local/bin/gdal2tiles.py -a 0 -z 5-12 {} {}'.format(file_cr, dir_tile), shell=True)
    #retun dir_tile

def merge_dirs(dir_input):
    for d in sorted(os.listdir(dir_input)):
        dir_in = os.path.join(dir_input, d)
        result = merge_dir(dir_in)
    # result should now be the results for the most current day
    dir_out = os.path.join(dir_input, 'tiled')
    if os.path.exists(dir_out):
        shutil.rmtree(dir_out)
    #shutil.move(result, dir_out)
    shutil.move(os.path.join(dir_in, 'tiled'), dir_out)

if __name__ == "__main__":
    simtimes, totaltime = run_fires()
    n = len(simtimes)
    if n > 0:
        logging.info("Total of {} fires took {}s - average time is {}s".format(n, totaltime, totaltime / n))
        merge_dirs('/FireGUARD/data/output/probability')
        merge_dirs('/FireGUARD/data/output/perimeter')
