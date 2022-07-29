# import libraries
import urllib.request as urllib2
from bs4 import BeautifulSoup
import pandas as pd
import os
import datetime
import sys
sys.path.append('../util')
import common
import tbd
import timeit
import logging
import shutil
import shlex
import sys
sys.path.append(os.path.dirname(sys.executable))
sys.path.append('/usr/local/bin')
import gdal_merge as gm
import itertools
import json

DIR = '/appl/data/fgmj/'
EXT_DIR = os.path.abspath(os.path.join(DIR, '../extracted/fgmj'))
common.ensure_dir(EXT_DIR)
CREATION_OPTIONS = ['COMPRESS=LZW', 'TILED=YES']

def getPage(url):
    logging.debug("Opening {}".format(url))
    # query the website and return the html to the variable 'page'
    page = urllib2.urlopen(url)
    # parse the html using beautiful soup and return
    return BeautifulSoup(page, 'html.parser')

def run_fires(site, region):
    site = 'https://cfsdip.intellifirenwt.com'
    region = 'canada'
    url = site + '/jobs/'
    try:
        p = getPage(url)
    except Exception as e:
        logging.error("Can't load {}".format(url))
        logging.error(e)
        return None
    a = p.findAll('a')
    dirs = [x.get('href') for x in a if x.get('href').startswith('/jobs/job_')]
    jobs = sorted(set([x[x.rindex('/') + 1:] for x in dirs]))
    times = {}
    recent = {}
    simtimes = {}
    dates = []
    totaltime = 0
    dir_download = common.ensure_dir(os.path.join(DIR, region))
    dir_ext = common.ensure_dir(os.path.join(EXT_DIR, region))
    logging.debug("Checking {} jobs".format(len(jobs)))
    by_fire = {}
    today = str(datetime.datetime.today()).replace('-', '')[:8]
    dates = [today]
    for j in jobs:
        if j.startswith("job_" + today):
            # job_p = getPage(url + j + "/Inputs")
            cur_dir = os.path.join(dir_download, j)
            fgmj = common.save_http(cur_dir, url + j + "/job.fgmj", ignore_existing=True)
            if os.path.exists(fgmj):
                with open(fgmj) as f:
                    data = json.load(f)
                scenario_name = data['project']['scenarios']['scenarios'][0]['name']
                fire_name = scenario_name[:scenario_name.index(' ')]
                if not fire_name in by_fire:
                    by_fire[fire_name] = []
                by_fire[fire_name] = by_fire[fire_name] + [fgmj]
    for fire_name in by_fire.keys():
        fgmj = sorted(by_fire[fire_name])[-1]
        cur_dir = os.path.dirname(fgmj)
        with open(fgmj) as f:
            data = json.load(f)
        wx_file = data['project']['stations']['stations'][0]['station']['streams'][0]['condition']['filename']
        wx = common.save_http(os.path.join(cur_dir, os.path.dirname(wx_file)), url + j + "/" + wx_file, ignore_existing=True)
        try:
            t0 = timeit.default_timer()
            log_name = tbd.do_run(fgmj)
            t1 = timeit.default_timer()
            if log_name is not None:
                simtimes[j] = t1 - t0
                totaltime = totaltime + simtimes[j]
                logging.info("Took {}s to run {}".format(simtimes[j], j))
                d = os.path.basename(os.path.dirname(log_name))[:8]
                if d not in dates:
                    dates.append(d)
        except Exception as e:
            logging.error(e)
    return simtimes, totaltime, dates

import gdal_retile as gr
import gdal_calc
import gdal

def merge_dir(dir_input):
    logging.debug("Merging {}".format(dir_input))
    # HACK: for some reason output tiles were both being called 'probability'
    import importlib
    importlib.reload(gr)
    TILE_SIZE = str(1024)
    file_tmp = dir_input + '_tmp.tif'
    file_out = dir_input + '.tif'
    file_int = dir_input + '_int.tif'
    co = list(itertools.chain.from_iterable(map(lambda x: ['-co', x], CREATION_OPTIONS)))
    files = []
    for region in os.listdir(dir_input):
        dir_region = os.path.join(dir_input, region)
        files = files + [os.path.join(dir_region, x) for x in sorted(os.listdir(dir_region)) if x.endswith('.tif')]
    gm.main(['', '-n', '0', '-a_nodata', '0'] + co + ['-o', file_tmp] + files)
    #gm.main(['', '-n', '0', '-a_nodata', '0', '-co', 'COMPRESS=DEFLATE', '-co', 'ZLEVEL=9', '-co', 'TILED=YES', '-o', file_tmp] + files)
    shutil.move(file_tmp, file_out)
    logging.debug("Calculating...")
    gdal_calc.Calc(A=file_out, outfile=file_tmp, calc='A*100', NoDataValue=0, type='Byte', creation_options=CREATION_OPTIONS, quiet=True)
    shutil.move(file_tmp, file_int)
    dir_tile = os.path.join(dir_input, 'tiled')
    if os.path.exists(dir_tile):
        logging.debug('Removing {}'.format(dir_tile))
        shutil.rmtree(dir_tile)
    import subprocess
    file_cr = dir_input + '_cr.tif'
    logging.debug("Applying symbology...")
    subprocess.run('gdaldem color-relief {} /appl/TBD/col.txt {} -alpha -co COMPRESS=LZW -co TILED=YES'.format(file_int, file_cr), shell=True)
    dir_tile = common.ensure_dir(dir_tile)
    subprocess.run('python /usr/local/bin/gdal2tiles.py -a 0 -z 5-12 {} {} --processes={}'.format(file_cr, dir_tile, os.cpu_count()), shell=True)
    #retun dir_tile

def merge_dirs(dir_input, dates=None):
    for d in sorted(os.listdir(dir_input)):
        if dates is None or d in dates:
            dir_in = os.path.join(dir_input, d)
            result = merge_dir(dir_in)
    # result should now be the results for the most current day
    dir_out = os.path.join(dir_input, 'tiled')
    if os.path.exists(dir_out):
        shutil.rmtree(dir_out)
    #shutil.move(result, dir_out)
    shutil.move(os.path.join(dir_in, 'tiled'), dir_out)
    # move and then copy from there since it shouldn't affect access for as long
    shutil.copytree(dir_out, os.path.join(dir_in, 'tiled'))

def run_all_fires():
    results = {}
    results['canada'] = run_fires('https://cfsdip.intellifirenwt.com', 'canada')
    simtimes = {}
    dates = []
    totaltime = 0
    for k in results.keys():
        if results[k] is not None:
            s, t, d = results[k]
            for f in s.keys():
                simtimes['{}_{}'.format(k, f)] = s[f]
            dates = sorted(dates + [x for x in d if x not in dates])
            totaltime = totaltime + t
    return simtimes, totaltime, dates

if __name__ == "__main__":
    simtimes, totaltime, dates = run_all_fires()
    n = len(simtimes)
    if n > 0:
        logging.info("Total of {} fires took {}s - average time is {}s".format(n, totaltime, totaltime / n))
        merge_dirs('/appl/data/output/probability', dates)
        merge_dirs('/appl/data/output/perimeter', dates)
