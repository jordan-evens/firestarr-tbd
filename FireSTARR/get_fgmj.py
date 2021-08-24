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
        firestarr.do_run(fgmj)
