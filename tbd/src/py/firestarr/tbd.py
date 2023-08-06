import math
import os
import re
import shlex
import timeit

import geopandas as gpd
import pandas as pd
from common import (
    DIR_TBD,
    SECONDS_PER_HOUR,
    WANT_DATES,
    ensure_dir,
    listdir_sorted,
    locks_for,
    logging,
    run_process,
)

import gis

# set to "" if want intensity grids
NO_INTENSITY = "--no-intensity"
# NO_INTENSITY = ""


def get_simulation_file(dir_fire):
    fire_name = os.path.basename(dir_fire)
    return os.path.join(dir_fire, f"firestarr_{fire_name}.geojson")


def run_fire_from_folder(dir_fire, dir_output, verbose=False):
    def nolog(*args, **kwargs):
        pass

    file_sim = get_simulation_file(dir_fire)
    # need directory for lock
    ensure_dir(os.path.dirname(file_sim))
    # lock before reading so if sim is running it will update file before lock ends
    with locks_for(file_sim):
        log_info = logging.info if verbose else nolog
        df_fire = gpd.read_file(file_sim)
        if 1 != len(df_fire):
            raise RuntimeError(f"Expected exactly one fire in file {file_sim}")
        data = df_fire.iloc[0]
        # check if completely done
        if data.get("postprocessed", False):
            df_fire["changed"] = False
            return df_fire
        changed = False
        fire_name = data["fire_name"]
        if not data.get("sim_time", None):
            lat = float(data["lat"])
            lon = float(data["lon"])
            start_time = pd.to_datetime(data["start_time"])
            log_info(f"Scenario start time is: {start_time}")
            if "Point" != data.geometry.geom_type:
                year = start_time.year
                reference = gis.find_best_raster(lon, year)
                raster = os.path.join(dir_fire, "{}.tif".format(fire_name))
                # FIX: if we never use points then the sims don't guarantee
                # running from non-fuel for the points like normally
                perim = gis.Rasterize(file_sim, raster, reference)
            else:
                # think this should be fine for using individual points
                gis.save_point_shp(lat, lon, dir_fire, fire_name)
                perim = None
            log_info("Startup coordinates are {}, {}".format(lat, lon))
            hour = start_time.hour
            minute = start_time.minute
            tz = start_time.tz.utcoffset(start_time).total_seconds() / SECONDS_PER_HOUR
            # HACK: I think there might be issues with forecasts being at the half hour?
            if math.floor(tz) != tz:
                # logging.warning("Rounding down to deal with partial hour timezone")
                tz = math.floor(tz)
            tz = int(tz)
            log_info("Timezone offset is {}".format(tz))
            start_date = start_time.date()
            cmd = os.path.join(DIR_TBD, "tbd")
            wx_file = os.path.join(dir_fire, data["wx"])
            want_dates = WANT_DATES
            max_days = data["max_days"]
            date_offsets = [x for x in want_dates if x <= max_days]
            fmt_offsets = "{" + ", ".join([str(x) for x in date_offsets]) + "}"
            file_log = file_sim.replace(".geojson", ".log")
            df_fire["log_file"] = file_log
            sim_time = None
            if os.path.exists(file_log):
                # if log says it ran then don't run it
                # HACK: just use tail instead of looping or seeking ourselves
                stdout, stderr = run_process(["tail", "-1", file_log], "/appl/tbd")
                if stdout:
                    line = stdout.strip().split("\n")[-1]
                    g = re.match(
                        ".*Total simulation time was (.*) seconds", line
                    ).groups()
                    if g:
                        sim_time = int(g[0])
            if not sim_time:

                def strip_dir(path):
                    p = os.path.abspath(path)
                    d = os.path.abspath(dir_fire)
                    if p.startswith(d):
                        p = p[len(d) + 1 :]
                    if 0 == len(p):
                        p = "."
                    return p

                stdout, stderr = None, None
                try:
                    args = " ".join(
                        [
                            f'"{strip_dir(dir_fire)}" {start_date} {lat} {lon}',
                            f"{hour:02d}:{minute:02d}",
                            NO_INTENSITY,
                            f"--ffmc {data['ffmc_old']}",
                            f"--dmc {data['dmc_old']}",
                            f"--dc {data['dc_old']}",
                            f"--apcp_prev {data['apcp_prev']}",
                            "-v",
                            f'--output_date_offsets "{fmt_offsets}"',
                            f"--wx {strip_dir(wx_file)}",
                            f"--log {strip_dir(file_log)}",
                        ]
                    )
                    if perim is not None:
                        args = args + f" --perim {strip_dir(perim)}"
                    args = args.replace("\\", "/")
                    file_sh = os.path.join(dir_fire, "sim.sh")
                    with open(file_sh, "w") as f_out:
                        f_out.writelines(["#!/bin/bash\n", f"{cmd} {args}\n"])
                    # NOTE: needs to be octal base
                    os.chmod(file_sh, 0o775)
                    log_info(f"Running: {cmd} {args}")
                    # run generated command for parsing data
                    run_what = [cmd] + shlex.split(args)
                    t0 = timeit.default_timer()
                    stdout, stderr = run_process(run_what, dir_fire)
                    t1 = timeit.default_timer()
                    sim_time = t1 - t0
                    log_info("Took {}s to run simulations".format(sim_time))
                    # if sim worked then it made a log itself so don't bother
                except Exception as ex:
                    # if sim failed we want to keep track of what happened
                    if stdout:
                        with open(file_log, "w") as f_log:
                            f_log.write(stdout)
                        with open(file_log.replace(".log", ".err.log"), "w") as f_log:
                            f_log.write(stderr)
                    raise ex
                df_fire["sim_time"] = sim_time
                gis.save_geojson(df_fire, file_sim)
                changed = True
        else:
            log_info("Simulation already ran but don't have processed outputs")
        # simulation was done or is now, but outputs don't exist
        logging.debug(f"Collecting outputs from {dir_fire}")
        outputs = listdir_sorted(dir_fire)
        extent = None
        probs = [
            x for x in outputs if x.endswith("tif") and x.startswith("probability")
        ]
        dates_out = []
        dir_region = os.path.join(dir_output, "initial")
        for prob in probs:
            logging.debug(f"Adding raster to final outputs: {prob}")
            # want to put each probability raster into right date so we can combine them
            d = prob[(prob.rindex("_") + 1) : prob.rindex(".tif")].replace("-", "")
            # NOTE: json doesn't work with datetime, so don't parse
            # dates_out.append(datetime.datetime.strptime(d, FMT_DATE))
            dates_out.append(d)
            # FIX: want all of these to be output at the size of the largest?
            # FIX: still doesn't show whole area that was simulated
            file_out = os.path.join(dir_region, d, fire_name + ".tif")
            if changed or not os.path.isfile(file_out):
                extent = gis.project_raster(
                    os.path.join(dir_fire, prob), file_out, nodata=None
                )
                # if file didn't exist then it's changed now
                changed = True
        perims = [
            x
            for x in outputs
            if (
                x.endswith("tif")
                and not (
                    x.startswith("probability")
                    or x.startswith("intensity")
                    or "dem.tif" == x
                    or "fuel.tif" == x
                )
            )
        ]
        if len(perims) > 0:
            file_out = os.path.join(dir_region, "perim", fire_name + ".tif")
            if changed or not os.path.isfile(file_out):
                perim = perims[0]
                log_info(f"Adding raster to final outputs: {perim}")
                gis.project_raster(
                    os.path.join(dir_fire, perim),
                    file_out,
                    outputBounds=extent,
                    # HACK: if nodata is none then 0's should just show up as 0?
                    nodata=None,
                )
                # if file didn't exist then it's changed now
                changed = True
        # geojson can't save list so make string
        df_fire["dates_out"] = f"{dates_out}"
        df_fire["postprocessed"] = True
        gis.save_geojson(df_fire, file_sim)
        # HACK: for some reason geojson can read a list as a column but not write it
        df_fire = gpd.read_file(file_sim)
        df_fire["changed"] = changed
        return df_fire
