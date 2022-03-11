"""Shared code"""

import math
import urllib.request as urllib2
import urllib.error
from urllib.parse import urlparse
import dateutil
import time
import dateutil.parser
import datetime
import os
import io
import subprocess
import shlex
import pandas as pd
import logging
import configparser
import re
import numpy as np
import shutil
import certifi
import ssl
import sys
import copy
import zipfile
import requests
from tqdm import tqdm

## So HTTPS transfers work properly
ssl._create_default_https_context = ssl._create_unverified_context

from urllib3.exceptions import InsecureRequestWarning
# Suppress only the single warning from urllib3 needed.
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

## bounds to use for clipping data
BOUNDS = None

## file to load settings from
SETTINGS_FILE = r'../settings.ini'
## loaded configuration
CONFIG = None

## @cond Doxygen_Suppress
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
## @endcond

def ensure_dir(dir):
    """!
    Check if directory exists and make it if not
    @param dir Directory to ensure existence of
    @return None
    """
    if not os.path.exists(dir):
        try:
            os.makedirs(dir)
        except:
            # screws up when threaded sometimes
            pass
    if not os.path.exists(dir):
        logging.fatal("Could not create directory {}".format(dir))
        sys.exit(-1)
    return dir


def to_utc(d):
    return pd.to_datetime(d, utc=True, infer_datetime_format=True)

def read_config(force=False):
    """!
    Read configuration from default file
    @param force Force reading even if already loaded
    @return None
    """
    global CONFIG
    global BOUNDS
    logging.debug('Reading config file {}'.format(SETTINGS_FILE))
    if force or CONFIG is None:
        CONFIG = configparser.SafeConfigParser()
        # set default values and then read to overwrite with whatever is in config
        CONFIG.add_section('tbd')
        # default to all of canada
        CONFIG.set('tbd', 'latitude_min', '41')
        CONFIG.set('tbd', 'latitude_max', '84')
        CONFIG.set('tbd', 'longitude_min', '-141')
        CONFIG.set('tbd', 'longitude_max', '-52')
        try:
            with open(SETTINGS_FILE) as configfile:
                CONFIG.readfp(configfile)
        except:
            logging.info('Creating new config file {}'.format(SETTINGS_FILE))
            with open(SETTINGS_FILE, 'w') as configfile:
                CONFIG.write(configfile)
        BOUNDS = {
            'latitude': {
                'min': int(CONFIG.get('tbd', 'latitude_min')),
                'max': int(CONFIG.get('tbd', 'latitude_max'))
            },
            'longitude': {
                'min': int(CONFIG.get('tbd', 'longitude_min')),
                'max': int(CONFIG.get('tbd', 'longitude_max'))
            }
        }


# HACK: need to do this every time file is loaded or else threads might get to it first
read_config()


def fix_timezone_offset(d):
    """!
    Convert from UTC to local time, respecting DST if required
    @param d Date to fix timezone offset for
    @return Date converted to local time
    """
    local_offset = time.timezone
    if time.daylight:
        if time.localtime().tm_isdst > 0:
            local_offset = time.altzone
    localdelta = datetime.timedelta(seconds=-local_offset)
    # convert to local time so other ftp programs would produce same result
    return (d + localdelta).replace(tzinfo=None)


def save_http(to_dir, url, save_as=None, mode='wb', ignore_existing=False):
    """!
    Save file at given URL into given directory using an HTTP connection
    @param to_dir Directory to save into
    @param url URL to download from
    @param save_as File to save as, or None to use URL file name
    @param mode Mode to write to file with
    @param ignore_existing Whether or not to download if file already exists
    @return Path that file was saved to
    """
    # logging.debug("Saving {}".format(url))
    if save_as is None:
        save_as = os.path.join(to_dir, os.path.basename(url))
    # print(save_as)
    if ignore_existing and os.path.exists(save_as):
        # logging.debug('Ignoring existing file')
        return save_as
    ensure_dir(to_dir)
    # we want to keep modified times matching on both ends
    do_save = True
    req = urllib2.Request(url, headers={'User-Agent': 'WeatherSHIELD/0.93'})
    response = urllib2.urlopen(req)
    modlocal = None
    if 'last-modified' in response.headers.keys():
        mod = response.headers['last-modified']
        modtime = dateutil.parser.parse(mod)
        modlocal = fix_timezone_offset(modtime)
        # if file exists then compare mod times
        if os.path.isfile(save_as):
            filetime = os.path.getmtime(save_as)
            filedatetime = datetime.datetime.fromtimestamp(filetime)
            do_save = modlocal != filedatetime
    # NOTE: need to check file size too? Or should it not matter because we
    #       only change the timestamp after it's fully written
    if do_save:
        logging.info("Downloading {}".format(save_as))
        try:
            response = requests.get(url, stream=True,verify=False)
            with tqdm.wrapattr(open(save_as, mode), "write",
                               miniters=1, desc=url.split('/')[-1],
                               total=int(response.headers.get('content-length', 0))) as fout:
                for chunk in response.iter_content(chunk_size=4096):
                    fout.write(chunk)
        except:
            try_remove(save_as)
            raise
        if modlocal is not None:
            tt = modlocal.timetuple()
            usetime = time.mktime(tt)
            os.utime(save_as, (usetime, usetime))
    return save_as


def save_ftp(to_dir, url, user="anonymous", password="", ignore_existing=False):
    """!
    Save file at given URL into given directory using an FTP connection
    @param to_dir Directory to save into
    @param url URL to download from
    @param user User to use for authentication
    @param password Password to use for authentication
    @param ignore_existing Whether or not to download if file already exists
    @return Path that file was saved to
    """
    urlp = urlparse(url)
    folder = os.path.dirname(urlp.path)
    site = urlp.netloc
    filename = os.path.basename(urlp.path)
    # logging.debug("Saving {}".format(filename))
    save_as = os.path.join(to_dir, filename)
    # print(save_as)
    if os.path.isfile(save_as):
        if ignore_existing:
            logging.debug('Ignoring existing file')
            return save_as
    import ftplib
    #logging.debug([to_dir, url, site, user, password])
    ftp = ftplib.FTP(site)
    ftp.login(user, password)
    ftp.cwd(folder)
    do_save = True
    ftptime = ftp.sendcmd('MDTM {}'.format(filename))
    ftpdatetime = datetime.datetime.strptime(ftptime[4:], '%Y%m%d%H%M%S')
    ftplocal = fix_timezone_offset(ftpdatetime)
    # if file exists then compare mod times
    if os.path.isfile(save_as):
        filetime = os.path.getmtime(save_as)
        filedatetime = datetime.datetime.fromtimestamp(filetime)
        do_save = ftplocal != filedatetime
    # NOTE: need to check file size too? Or should it not matter because we
    #       only change the timestamp after it's fully written
    if do_save:
        logging.debug("Downloading {}".format(filename))
        with open(save_as, 'wb') as f:
            ftp.retrbinary('RETR {}'.format(filename), f.write)
        tt = ftplocal.timetuple()
        usetime = time.mktime(tt)
        os.utime(save_as, (usetime, usetime))
    return save_as


def try_save(fct, url, max_save_retries=5):
    """!
    Use callback fct to try saving up to a fixed number of retries
    @param fct Function to apply to url
    @param url URL to apply function to
    @param max_save_retries Maximum number of times to try saving
    @return Result of calling fct on url
    """
    save_tries = 0
    while (True):
        try:
            return fct(url)
        except urllib.error.URLError as ex:
            logging.warning(ex)
            # no point in retrying if URL doesn't exist
            if 403 == ex.code:
                logging.error(ex.reason)
                raise ex
            if 404 == ex.code or save_tries >= max_save_retries:
                raise ex
            logging.warning("Retrying save for {}".format(url))
            save_tries += 1


def copy_file(filename, toname):
    """!
    Copy file and keep timestamp the same
    @param filename Source path to copy from
    @param toname Destination path to copy to
    @return None
    """
    shutil.copyfile(filename, toname)
    filetime = os.path.getmtime(filename)
    os.utime(toname, (filetime, filetime))


def calc_rh(Td, T):
    """!
    Calculate RH based on dewpoint temp and temp
    @param Td Dewpoint temperature (Celcius)
    @param T Temperature (Celcius)
    @return Relative Humidity (%)
    """
    m = 7.591386
    Tn = 240.7263
    return 100 * pow(10, (m * ((Td / (Td + Tn)) - (T / (T + Tn)))))


def calc_ws(u, v):
    """!
    Calculate wind speed in km/h from U and V wind given in m/s
    @param u Wind vector in U direction (m/s)
    @param v Wind vector in V direction (m/s)
    @return Calculated wind speed (km/h)
    """
    # NOTE: convert m/s to km/h
    return 3.6 * math.sqrt(u * u + v * v)


def calc_wd(u, v):
    """!
    Calculate wind direction from U and V wind given in m/s
    @param u Wind vector in U direction (m/s)
    @param v Wind vector in V direction (m/s)
    @return Wind direction (degrees)
    """
    return ((180 / math.pi * math.atan2(-u, -v)) + 360) % 360


def kelvin_to_celcius(t):
    """!
    Convert temperature in Kelvin to Celcius 
    @param t Temperature (Celcius)
    @return Temperature (Kelvin)
    """
    return t - 273.15

def apply_wind(w):
    return w.apply(calc_wind, axis=1)

def filterXY(data):
    data = data[data[:, :, 0] >= BOUNDS['latitude']['min']]
    data = data[data[:, 0] <= BOUNDS['latitude']['max']]
    data = data[data[:, 1] >= BOUNDS['longitude']['min']]
    data = data[data[:, 1] <= BOUNDS['longitude']['max']]
    return data

def read_all_data(lib, coords, mask, matches, indices):
# def read_data(args):
    # coords, mask, select, m = args
    # logging.debug('{} => {}'.format(mask.format(m), select))
    results = wgrib2.get_all_data(lib, mask, indices, matches)
    # now we have an array of all the ensemble members
    final = {}
    for m in results.keys():
        final[m] = []
        for r in results[m]:
            data = np.dstack([coords, r])
            data = filterXY(data)
            final[m].append(data[:, 2])
        # logging.debug("Slice")
    return final


k_to_c = np.vectorize(kelvin_to_celcius)


import concurrent.futures

# def read_member(mask, select, coords, member, apcp):
def read_members(lib, mask, matches, coords, members, apcp):
    indices = ['TMP', 'RH', 'UGRD', 'VGRD']
    if apcp:
        indices = indices + ['APCP']
    results = read_all_data(lib, coords, mask, matches, indices)
    temp = results['TMP']
    rh = results['RH']
    ugrd = results['UGRD']
    vgrd = results['VGRD']
    # temp = read_data(coords, mask, matches, 'TMP')
    # rh = read_data(coords, mask, matches, 'RH')
    # ugrd = read_data(coords, mask, matches, 'UGRD')
    # vgrd = read_data(coords, mask, matches, 'VGRD')
    # logging.debug("Kelvin")
    temp = k_to_c(temp)
    ws = []
    wd = []
    for u, v in zip(ugrd, vgrd):
        # logging.debug("Speed")
        u_2 = u * u
        v_2 = v * v
        sq = u_2 + v_2
        ws.append(3.6 * np.sqrt(sq))
        # logging.debug("Direction")
        a = np.arctan2(-u, -v)
        wd.append(((180 / math.pi * a) + 360) % 360)
    # logging.debug("Stack")
    columns = ['latitude', 'longitude', 'TMP','RH', 'WS', 'WD']
    if apcp:
        # pcp = read_data(coords, mask, matches, 'APCP')
        pcp = results['APCP']
    coords = filterXY(coords)
    # logging.debug("DataFrame")
    results = []
    for i in range(len(members)):
        member = members[i]
        wx = pd.DataFrame(coords, columns=['latitude', 'longitude'])
        wx['TMP'] = temp[i]
        wx['RH'] = rh[i]
        wx['WS'] = ws[i]
        wx['WD'] = wd[i]
        wx['APCP'] = pcp[i] if apcp else 0
        wx['Member'] = member
        results.append(wx)
    # logging.debug("Done")
    return pd.concat(results)

from multiprocessing import Pool

def read_grib(mask, apcp=True):
    """!
    Read grib data for desired time and field
    @param mask File mask for path to source grib2 file to read
    @return DataFrame with data read from file    
    """
    lib = wgrib2.open()
    matches = wgrib2.match(lib, mask.format('TMP'))
    members = list(map(lambda x: 0 if -1 != x.find('low-res ctl') else int(x[x.find('ENS=') + 4:]), matches))
    matches = list(map(lambda x: x[x.rfind(':'):], matches))
    coords = wgrib2.coords(lib, mask.format('TMP'))
    results = read_members(lib, mask, matches, coords, members, apcp)
    # logging.debug(output)
    output = results.set_index(['latitude', 'longitude', 'Member'])
    output = output[['TMP', 'RH', 'WS', 'WD', 'APCP']]
    # need to add fortime and generated
    wgrib2.close(lib)
    del lib
    return output

def try_remove(file):
    """!
    Delete file but ignore errors if can't while raising old error
    @param file Path to file to delete
    @return None
    """
    try:
        logging.debug("Trying to delete file {}".format(file))
        os.remove(file)
    except:
        pass


def download(url, suppress_exceptions=True):
    """!
    Download URL
    @param url URL to download
    @param suppress_exceptions Whether or not return exception instead of raising it
    @return Contents of URL, or exception
    """
    try:
        # HACK: check this to make sure url completion has worked properly
        assert('{}' not in url)
        response = urllib2.urlopen(url)
        # logging.debug("Saving {}".format(url))
        return response.read()
    except urllib.error.URLError as ex:
        # provide option so that we can call this from multiprocessing and still handle errors
        if suppress_exceptions:
            # HACK: return type and url for exception
            return {'type': type(ex), 'url': url}
        ex.url = url
        raise ex


def download_many(urls, fct=download):
    """!
    Download multiple URLs
    @param urls List of multiple URLs to download
    @param processes Number of processes to use for downloading
    @return List of paths that files have been saved to
    """
    results = list(map(fct, list(urls)))
    for i, result in enumerate(results):
        if isinstance(result, dict):
            # HACK: recreate error by trying to open it again
            # if this works this time then everything is fine right?
            results[i] = fct(get_what[i], suppress_exceptions=False)
    return results


def split_line(line):
    """!
    Split given line on whitespace sections
    @param line Line to split on whitespace
    @return Array of strings after splitting
    """
    return re.sub(r' +', ' ', line.strip()).split(' ')


def unzip(path, to_dir, match=None):
    if not os.path.exists(to_dir):
        os.mkdir(to_dir)
    with zipfile.ZipFile(path, 'r') as zip_ref:
        if match is None:
            zip_ref.extractall(to_dir)
        else:
            names = [x for x in zip_ref.namelist() if match in x]
            zip_ref.extractall(to_dir, names)

def start_process(run_what, cwd):
    """!
    Start running a command using subprocess
    @param run_what Process to run
    @param flags Flags to run with
    @param cwd Directory to run in
    @return Running subprocess
    """
    # logging.debug(run_what)
    p = subprocess.Popen(run_what,
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE,
                           cwd=cwd)
    p.args = run_what
    return p

def finish_process(process):
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        #HACK: seems to be the exit code for ctrl + c events loop tries to run it again before it exits without this
        if -1073741510 == process.returncode:
            sys.exit(process.returncode)
        raise Exception('Error running {} [{}]: '.format(process.args, process.returncode) + stderr.decode('utf-8') + stdout.decode('utf-8'))
    return stdout, stderr
