import sys
sys.path.append('../util')
from common import *
import json
import sys
import pandas as pd
import geopandas as gpd
import math
import datetime
import shlex
import timeit
from osgeo import ogr
from osgeo import osr
import statistics
from shapely.geometry import Polygon, mapping
import os
import gis
import numpy as np
import shutil


DIR_DATA = ensure_dir('/appl/data')
DIR_ROOT = ensure_dir(os.path.join(DIR_DATA, 'sims'))
DIR_OUTPUT = ensure_dir(os.path.join(DIR_DATA, 'output'))
FILE_SIM = "firestarr.json"
# set to "" if want intensity grids
NO_INTENSITY = "--no-intensity"
# NO_INTENSITY = ""


def run_fire_from_folder(dir_fire, dir_current, verbose=False):
    def nolog(*args, **kwargs):
        pass
    log_info = logging.info if verbose else nolog
    file_json = os.path.join(dir_fire, FILE_SIM)
    try:
        with open(file_json) as f:
            data = json.load(f)
            # check if completely done
            if data.get("postprocessed", False):
                return data
    except json.JSONDecodeError as ex:
        logging.error(f"Can't read config for {dir_fire}")
        logging.error(ex)
        raise ex
    region = os.path.basename(os.path.dirname(os.path.dirname(dir_fire)))
    dir_out = data['dir_out']
    job_date = data['job_date']
    fire_name = data['fire_name']
    # dir_out = os.path.join(ROOT_DIR, job_date, region, fire_name, job_time)
    # outputs = sorted(os.listdir(dir_out))
    # probs = [x for x in outputs if x.endswith('tif') and x.startswith('probability')]
    # done_already = len(probs) > 0
    done_already = data.get("ran", False)
    log_file = os.path.join(dir_out, "log.txt")
    data['log_file'] = log_file
    try:
        if not done_already:
            lat = data['lat']
            lon = data['lon']
            # job_name = os.path.basename(dir_in)
            # job_time = job_name[job_name.rindex('_') + 1:]
            # job_date = job_time[:8]
            job_time = data['job_time']
            start_time = data['start_time']
            start_time = pd.to_datetime(start_time)
            log_info("Scenario start time is: {}".format(start_time))
            # done_already = False
            # if not done_already:
            ensure_dir(dir_out)
            perim = data['perim']
            if perim is not None:
                perim = os.path.join(dir_fire, data['perim'])
                logging.debug(f'Perimeter input is {perim}')
                lyr = gpd.read_file(perim)
                out_file = gis.save_geojson(lyr, os.path.join(dir_out, fire_name))
                year = start_time.year
                reference = gis.find_best_raster(lon, year)
                raster = os.path.join(dir_out, "{}.tif".format(fire_name))
                # FIX: if we never use points then the sims don't guarantee
                # running from non-fuel for the points like normally
                perim = gis.Rasterize(perim, raster, reference)
            else:
                gis.save_point_shp(lat, lon, dir_out, fire_name)
                sys.exit(-1)
            log_info("Startup coordinates are {}, {}".format(lat, lon))
            hour = start_time.hour
            minute = start_time.minute
            tz = start_time.tz.utcoffset(start_time).total_seconds() / 60.0 / 60.0
            # HACK: I think there might be issues with forecasts being at the half hour?
            if math.floor(tz) != tz:
                logging.fatal("Currently not set up to deal with partial hour timezones")
                sys.exit(-1)
            tz = int(tz)
            log_info("Timezone offset is {}".format(tz))
            # date_offset = 0
            start_date = start_time.date()
            # if start_date != datetime.date.today():
            #     date_offset = (start_date - datetime.date.today()).days
            #     logging.warning("Simulation does not start today - date offset set to {}".format(date_offset))
            cmd = "./tbd"
            wx_file = os.path.join(dir_out, 'wx.csv')
            shutil.copy(os.path.join(dir_fire, data['wx']), wx_file)
            # date_offsets = [1, 2]
            date_offsets = data['offsets']
            fmt_offsets = "{" + ", ".join([str(x) for x in date_offsets]) + "}"
            args = ' '.join([
                    f"\"{dir_out}\" {start_date} {lat} {lon}",
                    f"{hour:02d}:{minute:02d}",
                    NO_INTENSITY,
                    f"--ffmc {data['ffmc_old']}",
                    f"--dmc {data['dmc_old']}",
                    f"--dc {data['dc_old']}",
                    f"--apcp_prev {data['apcp_prev']}",
                    f"-v --output_date_offsets \"{fmt_offsets}\"",
                    f" --wx \"{wx_file}\""
            ])
            if perim is not None:
                args = args + " --perim \"{}\"".format(perim)
            args = args.replace('\\', '/')
            file_sh = os.path.join(dir_out, "sim.sh")
            with open(file_sh, "w") as f_out:
                f_out.writelines(
                    [
                        "#!/bin/bash\n",
                        f"{cmd} {args}\n"
                    ]
                )
            # NOTE: needs to be octal base
            os.chmod(file_sh, 0o775)
            log_info(f'Running: {cmd} {args}')
            # run generated command for parsing data
            run_what = [cmd] + shlex.split(args)
            t0 = timeit.default_timer()
            stdout, stderr = finish_process(start_process(run_what, "/appl/tbd"))
            t1 = timeit.default_timer()
            sim_time = t1 - t0
            data['sim_time'] = sim_time
            data['sim_finished'] = True
            file_json = dump_json(data, file_json)
            data["ran"] = True
            log_info("Took {}s to run simulations".format(sim_time))
            with open(log_file, 'w') as f_log:
                f_log.write(stdout.decode('utf-8'))
        else:
            log_info("Simulation already ran")
            data['sim_time'] = None
        logging.debug(f"Collecting outputs from {dir_out}")
        outputs = sorted(os.listdir(dir_out))
        extent = None
        probs = [x for x in outputs if x.endswith('tif') and x.startswith('probability')]
        dates_out = []
        dir_region = os.path.join(dir_current, "initial", job_date, region)
        for prob in probs:
            logging.debug(f"Adding raster to final outputs: {prob}")
            # want to put each probability raster into the right date so we can combine them
            d = prob[(prob.rindex('_') + 1):prob.rindex('.tif')].replace('-', '')
            # NOTE: json doesn't work with datetime, so don't parse
            # dates_out.append(datetime.datetime.strptime(d, "%Y%m%d"))
            dates_out.append(d)
            # FIX: want all of these to be output at the size of the largest?
            # FIX: still doesn't show whole area that was simulated
            file_out = os.path.join(dir_region, d, fire_name + '.tif')
            if data.get("ran", False) or not os.path.isfile(file_out):
                extent = gis.project_raster(
                    os.path.join(dir_out, prob),
                    file_out,
                    nodata=None
            )
        perims = [x for x in outputs if (
            x.endswith('tif')
            and not (
                x.startswith('probability')
                or x.startswith('intensity')
                or 'dem.tif' == x
                or 'fuel.tif' == x
            )
        )]
        if len(perims) > 0:
            # FIX: maybe put the perims used for the run and the outputs in the same root directory?
            file_out = os.path.join(dir_region, 'perim', fire_name + '.tif')
            if data.get("ran", False) or not os.path.isfile(file_out):
                perim = perims[0]
                log_info(f"Adding raster to final outputs: {perim}")
                gis.project_raster(os.path.join(dir_out, perim),
                                                file_out,
                                                outputBounds=extent,
                                                # HACK: if nodata is none then 0's should just show up as 0?
                                                nodata=None)
        data['dates_out'] = dates_out
        data['postprocessed'] = True
        file_json = dump_json(data, file_json)
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        logging.warning(ex)
        data['sim_time'] = None
        data['sim_finished'] = False
        data['dates_out'] = None
        data['postprocessed'] = False
        # FIX: should we return e here?
    return data


if __name__ == "__main__":
    if 1 < len(sys.argv):
        dir_fire = sys.argv[1]
        if 2 < len(sys.argv):
            dir_current = sys.argv[2]
        else:
            run_folder = os.path.dirname(dir_fire)
            run_prefix = run_folder[:run_folder.find('_')]
            dir_current = os.path.join(DIR_OUTPUT, f"current_{run_prefix}")
        data = run_fire_from_folder(dir_fire, dir_current, verbose=True)
        logging.info(f"Running fire in {dir_fire} completed")
        if isinstance(data, Exception):
            raise data
        dates = [datetime.datetime.strftime(x, '%Y-%m-%d') for x in data['dates_out']]
        logging.info(f"Produced results for days: [{', '.join(dates)}]")
        logging.info(f"Outputs are in {data['dir_out']}")
        logging.info(f"Log file is {data['log_file']}")
    else:
        logging.fatal("Must specify folder to run fire from")
