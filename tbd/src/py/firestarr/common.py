"""Shared code"""
import configparser
import datetime
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from functools import cache
from logging import getLogger

import numpy as np
import pandas as pd
import tqdm_util
from log import logging
from osgeo import gdal

FLAG_DEBUG = False

FMT_DATETIME = "%Y-%m-%d %H:%M:%S"
FMT_DATE_YMD = "%Y%m%d"
FMT_TIME = "%H%M"

# makes groups that are too big because it joins mutiple groups into a chain
# DEFAULT_GROUP_DISTANCE_KM = 60
# also too big
# DEFAULT_GROUP_DISTANCE_KM = 40
DEFAULT_GROUP_DISTANCE_KM = 20
# MAX_NUM_DAYS = 3
# MAX_NUM_DAYS = 7
MAX_NUM_DAYS = 14
# DEFAULT_M3_LAST_ACTIVE = None
DEFAULT_M3_LAST_ACTIVE = datetime.timedelta(days=30)
DEFAULT_M3_UNMATCHED_LAST_ACTIVE_IN_DAYS = 1

PUBLISH_AZURE_WAIT_TIME_SECONDS = 10

# FORMAT_OUTPUT = "COG"
FORMAT_OUTPUT = "GTiff"

USE_CWFIS_SERVICE = False
TIMEDELTA_DAY = datetime.timedelta(days=1)
TIMEDELTA_HOUR = datetime.timedelta(hours=1)

# use default for pmap() if None
# CONCURRENT_SIMS = None
# # HACK: try just running a few at a time since time limit is low
CONCURRENT_SIMS = max(1, tqdm_util.MAX_PROCESSES // 2)

CREATION_OPTIONS = [
    "COMPRESS=LZW",
    "TILED=YES",
    "BLOCKSIZE=512",
    "OVERVIEWS=AUTO",
    "NUM_THREADS=ALL_CPUS",
]
WANT_DATES = [1, 2, 3, 7, 14]

# was still getting messages that look like they're from gdal when debug is on, but
# maybe they're from a package that's using it?

gdal.UseExceptions()
gdal.SetConfigOption("CPL_LOG", "/dev/null")
gdal.SetConfigOption("CPL_DEBUG", "OFF")
gdal.PushErrorHandler("CPLQuietErrorHandler")

getLogger("gdal").setLevel(logging.WARNING)
getLogger("fiona").setLevel(logging.WARNING)

# bounds to use for clipping data
BOUNDS = None

# file to load settings from
SETTINGS_FILE = r"../config"
# loaded configuration
CONFIG = None

DEFAULT_FILE_LOG_LEVEL = logging.DEBUG
# DEFAULT_FILE_LOG_LEVEL = logging.INFO


def ensure_dir(dir):
    """!
    Check if directory exists and make it if not
    @param dir Directory to ensure existence of
    @return None
    """
    os.makedirs(dir, exist_ok=True)
    if not os.path.isdir(dir):
        logging.fatal("Could not create directory {}".format(dir))
        sys.exit(-1)
    return dir


DIR_SRC_PY_FIRSTARR = os.path.dirname(__file__)
DIR_SRC_PY = os.path.dirname(DIR_SRC_PY_FIRSTARR)
DIR_SRC_PY_CFFDRSNG = os.path.join(DIR_SRC_PY, "cffdrs-ng")
sys.path.append(DIR_SRC_PY_CFFDRSNG)

DIR_SCRIPTS = "/appl/tbd/scripts"

DIR_DATA = ensure_dir(os.path.abspath("/appl/data"))
DIR_DOWNLOAD = ensure_dir(os.path.join(DIR_DATA, "download"))
DIR_LOG = ensure_dir(os.path.join(DIR_DATA, "logs"))
DIR_SIMS = ensure_dir(os.path.join(DIR_DATA, "sims"))
DIR_OUTPUT = ensure_dir(os.path.join(DIR_DATA, "output"))
DIR_ZIP = ensure_dir(os.path.join(DIR_DATA, "zip"))


def listdir_sorted(path):
    return sorted(os.listdir(path))


def list_dirs(path):
    return [x for x in listdir_sorted(path) if os.path.isdir(os.path.join(path, x))]


def to_utc(d):
    return pd.to_datetime(d, errors="coerce", utc=True)


def read_config(force=False):
    """!
    Read configuration from default file
    @param force Force reading even if already loaded
    @return None
    """
    global CONFIG
    global BOUNDS
    logging.debug("Reading config file {}".format(SETTINGS_FILE))
    if force or CONFIG is None:
        # default to all of canada
        CONFIG = {
            "BOUNDS_LATITUDE_MIN": "41",
            "BOUNDS_LATITUDE_MAX": "84",
            "BOUNDS_LONGITUDE_MIN": "-141",
            "BOUNDS_LONGITUDE_MAX": "-52",
            "BOUNDS_FILE": "",
            "SPOTWX_API_KEY": "",
            "SPOTWX_API_LIMITs": "150",
            "AZURE_URL": "",
            "AZURE_TOKEN": "",
            "AZURE_CONTAINER": "",
            "GEOSERVER_LAYER": "",
            "GEOSERVER_COVERAGE": "",
            "GEOSERVER_CREDENTIALS": "",
            "GEOSERVER_SERVER": "",
            "GEOSERVER_WORKSPACE": "",
            "GEOSERVER_DIR_DATA": "",
        }
        config = configparser.ConfigParser()
        # set default values and then read to overwrite with whatever is in config
        config.add_section("GLOBAL")
        for k, v in CONFIG.items():
            config.set("GLOBAL", k, v)
        try:
            with open(SETTINGS_FILE) as configfile:
                # fake a config section so it works with parser
                config.read_file(
                    itertools.chain(["[GLOBAL]"], configfile), source=SETTINGS_FILE
                )
        except KeyboardInterrupt as ex:
            raise ex
        except Exception:
            logging.info("Creating new config file {}".format(SETTINGS_FILE))
            # HACK: don't output section header because it breaks bash
            from io import StringIO

            buffer = StringIO()
            config.write(buffer)
            buffer.seek(0)
            fixed = []
            # skip header and last empty line
            for line in buffer.readlines()[1:-1]:
                split = line.strip("\n").split(" = ")
                # HACK: if for some reason the value has " = " in it then 2 < len(split)
                k = split[0]
                v = " = ".join(split[1:])
                fixed.append(f"{k.upper()}={v}\n")
            with open(SETTINGS_FILE, "w") as f:
                f.writelines(fixed)
        # assign to CONFIG so defaults get overwritten
        for k, v in config.items("GLOBAL"):
            v = v.strip('"') if v.startswith('"') and v.endswith('"') else v.strip("'")
            CONFIG[k.upper()] = v
        BOUNDS = {
            "latitude": {
                "min": float(CONFIG["BOUNDS_LATITUDE_MIN"]),
                "max": float(CONFIG["BOUNDS_LATITUDE_MAX"]),
            },
            "longitude": {
                "min": float(CONFIG["BOUNDS_LONGITUDE_MIN"]),
                "max": float(CONFIG["BOUNDS_LONGITUDE_MAX"]),
            },
            "bounds": CONFIG["BOUNDS_FILE"],
        }
        for k in ["latitude", "longitude"]:
            high, low = BOUNDS[k]["max"], BOUNDS[k]["min"]
            BOUNDS[k]["mid"] = (high - low) / 2 + low


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


def filterXY(data):
    data = data[data[:, :, 0] >= BOUNDS["latitude"]["min"]]
    data = data[data[:, 0] <= BOUNDS["latitude"]["max"]]
    data = data[data[:, 1] >= BOUNDS["longitude"]["min"]]
    data = data[data[:, 1] <= BOUNDS["longitude"]["max"]]
    return data


def try_remove(path):
    """!
    Delete path but ignore errors if can't while raising old error
    @param path Path to delete
    @return None
    """
    if not FLAG_DEBUG and path:
        try:
            if os.path.isfile(path):
                logging.debug("Trying to delete file {}".format(path))
                os.remove(path)
            elif os.path.isdir(path):
                logging.debug("Trying to remove directory {}".format(path))
                shutil.rmtree(path, ignore_errors=True)
        except KeyboardInterrupt as ex:
            raise ex
        except Exception:
            pass


def split_line(line):
    """!
    Split given line on whitespace sections
    @param line Line to split on whitespace
    @return Array of strings after splitting
    """
    return re.sub(r" +", " ", line.strip()).split(" ")


def unzip(path, to_dir, match=None):
    if not os.path.exists(to_dir):
        os.mkdir(to_dir)
    with zipfile.ZipFile(path, "r") as zip_ref:
        if match is None:
            names = zip_ref.namelist()
            zip_ref.extractall(to_dir)
        else:
            names = [x for x in zip_ref.namelist() if match in x]
            zip_ref.extractall(to_dir, names)
    return [os.path.join(to_dir, x) for x in names]


def start_process(run_what, cwd):
    """!
    Start running a command using subprocess
    @param run_what Process to run
    @param flags Flags to run with
    @param cwd Directory to run in
    @return Running subprocess
    """
    # logging.debug(run_what)
    p = subprocess.Popen(
        run_what, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd
    )
    p.args = run_what
    return p


def finish_process(process):
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        # HACK: seems to be the exit code for ctrl + c events loop tries to run
        # it again before it exits without this
        if -1073741510 == process.returncode:
            sys.exit(process.returncode)
        raise RuntimeError(
            "Error running {} [{}]: ".format(process.args, process.returncode)
            + stderr.decode("utf-8")
            + stdout.decode("utf-8")
        )
    return stdout, stderr


def zip_folder(zip_name, path):
    with zipfile.ZipFile(zip_name, "w") as zf:
        all_files = []
        logging.info("Finding files")
        for root, dirs, files in os.walk(path):
            for d in dirs:
                dir = os.path.join(root, d)
                zf.write(dir, dir.replace(path, "").lstrip("/"))
            for f in files:
                all_files.append(os.path.join(root, f))
        logging.info("Zipping")
        for f in tqdm_util.apply(all_files, desc=os.path.basename(zip_name)):
            f_relative = f.replace(path, "").lstrip("/")
            zf.write(f, f_relative, zipfile.ZIP_DEFLATED)
        return zip_name


def dump_json(data, path):
    try:
        dir = os.path.dirname(path)
        base = os.path.splitext(os.path.basename(path))[0]
        file = os.path.join(dir, f"{base}.json")
        # NOTE: json.dumps() first and then write string so
        #      file is okay if dump fails
        # FIX: this is overkill but just want it to work for now
        s = json.dumps(data)
        json.loads(s)
        with open(file, "w") as f:
            # HACK: not getting full string when using f.write(s)
            json.dump(data, f)
            # f.write(s)
    except Exception as ex:
        logging.error(f"Error writing to {file}:\n{str(ex)}\n{data}")
        raise ex
    return file


def pick_max(a, b):
    return np.max(list(zip(a, b)), axis=1)


def pick_max_by_column(a, b, column, index=None):
    # these need to match, so assume index of a if not specified
    if index is None:
        index = a.index
    return pick_max(a.loc[index, column], b.loc[index, column])


# standard function we can use as a default wrapper if nothing special happens
def do_nothing(x):
    return x


@cache
def calc_offset(d, i):
    return d + datetime.timedelta(days=i)


class Origin(object):
    def __init__(self, d=None):
        if d is None:
            d = datetime.date.today()
        # HACK: don't check for class because hopefully this works with anything
        if hasattr(d, "date"):
            if callable(d.date):
                d = d.date()
            else:
                d = d.date
        self._today = d

    def offset(self, i):
        return calc_offset(self._today, i)

    @property
    def today(self):
        return self._today

    @property
    def yesterday(self):
        return self.offset(-1)

    @property
    def tomorrow(self):
        return self.offset(1)
