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

import sys
sys.path.append(os.path.dirname(sys.executable))
sys.path.append('/usr/local/bin')
import gdal_merge as gm

SITE = 'http://psaasbc.dss.intellifirenwt.com'
URL = SITE + '/jobs/archive/'
DIR = '/FireGUARD/data/fgmj/'
EXT_DIR = os.path.abspath(os.path.join(DIR, '../extracted/fgmj'))
common.ensure_dir(EXT_DIR)

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

def merge_dir(dir):
    files = [os.path.join(dir, x) for x in sorted(os.listdir(dir))]
    gm.main(['', '-n', '0', '-a_nodata', '0', '-co', 'COMPRESS=LZW', '-co', 'TILED=YES', '-o', dir + '.tif'] + files)
    # gm.main(['', '-co', 'COMPRESS=LZW', '-co', 'TILED=YES', '-o', dir + '.tif'] + files)
    # gm.main(['', '-o', dir + '.tif'] + files)

n = len(simtimes)
if n > 0:
    logging.info("Total of {} fires took {}s - average time is {}s".format(n, totaltime, totaltime / n))
    merge_dir('/FireGUARD/data/output/perimeter')
    merge_dir('/FireGUARD/data/output/probability')
