import math
import os
import re
import time
import timeit

import pandas as pd
import psutil
from azurebatch.batch_container import add_simulation_task, check_task_running

# from azurebatch.batch_container import (
#     add_job,
#     get_batch_client,
#     have_batch_config,
# )
# from common import DIR_SIMS
from common import (
    DIR_DATA,
    DIR_TBD,
    SECONDS_PER_HOUR,
    WANT_DATES,
    ensure_dir,
    listdir_sorted,
    locks_for,
    logging,
    run_process,
)
from gis import (
    Rasterize,
    find_best_raster,
    project_raster,
    read_gpd_file_safe,
    save_geojson,
    save_point_shp,
)
from redundancy import call_safe

# set to "" if want intensity grids
NO_INTENSITY = "--no-intensity"
# NO_INTENSITY = ""

TASK_SLEEP = 5

_RUN_FIRESTARR = None
_CHECK_RUNNING = None
_BATCH_CLIENT = None
_JOB_ID = None


def run_firestarr_local(dir_fire):
    stdout, stderr = None, None
    try:
        stdout, stderr = run_process(["./sim.sh"], dir_fire)
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        # if sim failed we want to keep track of what happened
        if stdout:

            def save_logs(*args, **kwargs):
                with open(os.path.join(dir_fire, "stdout.log"), "w") as f_log:
                    f_log.write(stdout)
                with open(os.path.join(dir_fire, "stderr.log"), "w") as f_log:
                    f_log.write(stderr)

            call_safe(save_logs)
        raise ex


def check_running_local(dir_fire):
    processes = []
    for p in psutil.process_iter():
        try:
            if p.name() == "tbd" and p.cwd() == dir_fire:
                processes.append(
                    p.as_dict(attrs=["cpu_times", "name", "pid", "status"])
                )
        except psutil.NoSuchProcess:
            continue
    return 0 < len(processes)


def run_firestarr_batch(dir_fire):
    task_id = add_simulation_task(_BATCH_CLIENT, _JOB_ID, dir_fire)
    while check_task_running(_BATCH_CLIENT, _JOB_ID, task_id):
        time.sleep(TASK_SLEEP)


def check_running_batch(dir_fire):
    return check_task_running(_BATCH_CLIENT, _JOB_ID, dir_fire)


def assign_firestarr_batch(dir_fire):
    global _RUN_FIRESTARR
    global _CHECK_RUNNING
    global _BATCH_CLIENT
    global _JOB_ID
    with locks_for(os.path.join(DIR_DATA, "assign_batch_client")):
        # if have_batch_config():
        #     _RUN_FIRESTARR = run_firestarr_batch
        #     _BATCH_CLIENT = get_batch_client()
        #     job_id = None
        #     if dir_fire.startswith(DIR_SIMS):
        #         job_id = dir_fire.replace(DIR_SIMS, "").strip("/")
        #         job_id = job_id[: job_id.index("/")]
        #     _JOB_ID = add_job(_BATCH_CLIENT, job_id=job_id)
        #     _CHECK_RUNNING = check_running_batch
        #     return True
        _RUN_FIRESTARR = run_firestarr_local
        _CHECK_RUNNING = check_running_local
        return False


def check_firestarr_batch(dir_fire):
    with locks_for(os.path.join(DIR_DATA, "check_batch_client")):
        if _RUN_FIRESTARR is None:
            assign_firestarr_batch(dir_fire)
    return _RUN_FIRESTARR(dir_fire)


def check_firestarr_running(dir_fire):
    with locks_for(os.path.join(DIR_DATA, "check_batch_client")):
        if _CHECK_RUNNING is None:
            assign_firestarr_batch(dir_fire)
    return _CHECK_RUNNING(dir_fire)


def run_firestarr(dir_fire):
    # run generated command for parsing data
    t0 = timeit.default_timer()
    # expect everything to be in sim.sh
    (_RUN_FIRESTARR or check_firestarr_batch)(dir_fire)
    t1 = timeit.default_timer()
    sim_time = t1 - t0
    return sim_time


def check_running(dir_fire):
    return (_CHECK_RUNNING or check_firestarr_running)(dir_fire)


def get_simulation_file(dir_fire):
    fire_name = os.path.basename(dir_fire)
    return os.path.join(dir_fire, f"firestarr_{fire_name}.geojson")


def copy_fire_outputs(dir_fire, dir_output, changed, suffix=""):
    # simulation was done or is now, but outputs don't exist
    logging.debug(f"Collecting outputs from {dir_fire}")
    fire_name = os.path.basename(dir_fire)
    outputs = listdir_sorted(dir_fire)
    extent = None
    probs = [x for x in outputs if x.endswith("tif") and x.startswith("probability")]
    dir_region = ensure_dir(os.path.join(dir_output, "initial"))
    for prob in probs:
        logging.debug(f"Adding raster to final outputs: {prob}")
        # want to put each probability raster into right date so we can combine them
        d = prob[(prob.rindex("_") + 1) : prob.rindex(".tif")].replace("-", "")
        # FIX: want all of these to be output at the size of the largest?
        # FIX: still doesn't show whole area that was simulated
        file_out = os.path.join(dir_region, d, f"{fire_name}{suffix}.tif")
        if changed or not os.path.isfile(file_out):
            extent = project_raster(os.path.join(dir_fire, prob), file_out, nodata=None)
            if extent is None:
                raise RuntimeError(f"Fire {dir_fire} has invalid output file {prob}")
            # if file didn't exist then it's changed now
            changed = True
    perims = [
        x
        for x in outputs
        if (
            x.endswith("tif")
            and not (
                x.startswith("probability")
                or x.startswith("interim")
                or x.startswith("intensity")
                or "dem.tif" == x
                or "fuel.tif" == x
            )
        )
    ]
    if len(perims) > 0:
        file_out = os.path.join(dir_region, "perim", f"{fire_name}{suffix}.tif")
        if changed or not os.path.isfile(file_out):
            perim = perims[0]
            logging.debug(f"Adding raster to final outputs: {perim}")
            extent = project_raster(
                os.path.join(dir_fire, perim),
                file_out,
                outputBounds=extent,
                # HACK: if nodata is none then 0's should just show up as 0?
                nodata=None,
            )
            if extent is None:
                raise RuntimeError(f"Fire {dir_fire} has invalid output file {perim}")
            # if file didn't exist then it's changed now
            changed = True
    return changed


def run_fire_from_folder(dir_fire, dir_output, verbose=False, prepare_only=False):
    def nolog(*args, **kwargs):
        pass

    def dolog(msg, *args, **kwargs):
        logging.info(f"{dir_fire}: {msg}", *args, **kwargs)

    log_info = dolog if verbose else nolog

    was_running = check_running(dir_fire)
    if was_running:
        log_info(f"Already running {dir_fire} - waiting for it to finish")
    while check_running(dir_fire):
        time.sleep(10)
    if was_running:
        log_info(f"Continuing after {dir_fire} finished running")

    file_sim = get_simulation_file(dir_fire)
    # need directory for lock
    ensure_dir(os.path.dirname(file_sim))
    # lock before reading so if sim is running it will update file before lock ends
    with locks_for(file_sim):
        df_fire = read_gpd_file_safe(file_sim) if os.path.isfile(file_sim) else None
        if df_fire is None:
            raise RuntimeError(f"Couldn't get fire data from {file_sim}")
        if 1 != len(df_fire):
            raise RuntimeError(f"Expected exactly one fire in file {file_sim}")
        data = df_fire.iloc[0]
        # check if completely done
        # if data.get("postprocessed", False):
        #     df_fire["changed"] = False
        #     return df_fire
        changed = False
        fire_name = data["fire_name"]
        # file_log = file_sim.replace(".geojson", ".log")
        file_log = os.path.join(dir_fire, "firestarr.log")
        sim_time = data.get("sim_time", None)
        if not sim_time:
            # try parsing log for simulation time
            sim_time = None
            if os.path.exists(file_log):
                # if log says it ran then don't run it
                # HACK: just use tail instead of looping or seeking ourselves
                stdout, stderr = run_process(["tail", "-1", file_log], "/appl/tbd")
                if stdout:
                    line = stdout.strip().split("\n")[-1]
                    g = re.match(".*Total simulation time was (.*) seconds", line)
                    if g and g.groups():
                        sim_time = int(g.groups()[0])
        want_dates = WANT_DATES
        max_days = data["max_days"]
        date_offsets = [x for x in want_dates if x <= max_days]
        # HACK: rerun if not enough outputs
        outputs = listdir_sorted(dir_fire)
        probs = [
            x for x in outputs if x.endswith("tif") and x.startswith("probability")
        ]
        if not sim_time or len(probs) != len(date_offsets):
            lat = float(data["lat"])
            lon = float(data["lon"])
            start_time = pd.to_datetime(data["start_time"])
            log_info(f"Scenario start time is: {start_time}")
            if "Point" != data.geometry.geom_type:
                year = start_time.year
                reference = find_best_raster(lon, year)
                raster = os.path.join(dir_fire, "{}.tif".format(fire_name))
                with locks_for(raster):
                    # FIX: if we never use points then the sims don't guarantee
                    # running from non-fuel for the points like normally
                    perim = call_safe(Rasterize, file_sim, raster, reference)
            else:
                # think this should be fine for using individual points
                save_point_shp(lat, lon, dir_fire, fire_name)
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
            # want format like a list with no spaces
            fmt_offsets = "[" + ",".join([str(x) for x in date_offsets]) + "]"

            def strip_dir(path):
                p = os.path.abspath(path)
                d = os.path.abspath(dir_fire)
                if p.startswith(d):
                    p = p[len(d) + 1 :]
                if 0 == len(p):
                    p = "."
                return p

            # FIX: --log doesn't work right now
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
                    f"--output_date_offsets {fmt_offsets}",
                    f"--wx {strip_dir(wx_file)}",
                    # f"--log {strip_dir(file_log)}",
                ]
            )
            if perim is not None:
                args = args + f" --perim {strip_dir(perim)}"
            args = args.replace("\\", "/")
            file_sh = os.path.join(dir_fire, "sim.sh")

            def mk_sim_sh(*a, **k):
                with open(file_sh, "w") as f_out:
                    f_out.writelines(["#!/bin/bash\n", f"{cmd} {args}\n"])

            call_safe(mk_sim_sh)
            # NOTE: needs to be octal base
            os.chmod(file_sh, 0o775)
            if prepare_only:
                return None
            log_info(f"Running: {cmd} {args}")
            sim_time = run_firestarr(dir_fire)
            log_info("Took {}s to run simulations".format(sim_time))
            # if sim worked then it made a log itself so don't bother
            df_fire["log_file"] = file_log
            df_fire["sim_time"] = sim_time
            if "dates_out" in df_fire.columns:
                del df_fire["dates_out"]
            save_geojson(df_fire, file_sim)
            changed = True
        else:
            # log_info("Simulation already ran but don't have processed outputs")
            log_info("Simulation already ran")
        changed = copy_fire_outputs(dir_fire, dir_output, changed)
        df_fire["changed"] = changed
        return df_fire
