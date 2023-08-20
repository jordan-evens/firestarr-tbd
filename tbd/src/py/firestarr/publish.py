import datetime
import itertools
import os
import shutil
import time

from common import (
    CREATION_OPTIONS,
    DIR_OUTPUT,
    DIR_SIMS,
    DIR_TMP,
    DIR_ZIP,
    FMT_DATE_YMD,
    FORMAT_OUTPUT,
    PUBLISH_AZURE_WAIT_TIME_SECONDS,
    ensure_dir,
    ensures,
    list_dirs,
    listdir_sorted,
    logging,
    zip_folder,
)
from gdal_merge_max import gdal_merge_max
from gis import CRS_COMPARISON, find_invalid_tiffs, project_raster
from redundancy import NUM_RETRIES, call_safe, get_stack
from tqdm_util import tqdm

from tbd import copy_fire_outputs, find_outputs, find_running

TMP_SUFFIX = "__tmp__"


def merge_safe(*args, **kwargs):
    return call_safe(gdal_merge_max, *args, **kwargs)


def check_copy_interim(dir_output, include_interim):
    if not include_interim:
        return
    if isinstance(include_interim, bool):
        # find running fires
        if not dir_output.startswith(DIR_OUTPUT):
            raise RuntimeError(
                f"Expected output directory to start with {DIR_OUTPUT}"
                f"but got {dir_output}"
            )
        run_name = os.path.basename(dir_output)
        dir_sim = os.path.join(DIR_SIMS, run_name)
        dirs_fire = find_running(dir_sim)
    else:
        dirs_fire = include_interim
    dir_tmp = ensure_dir(os.path.join(DIR_TMP, os.path.basename(dir_output), "interim"))

    def find_files_tmp():
        files_tmp = []
        for root, dirs, files in os.walk(dir_output):
            for f in files:
                if TMP_SUFFIX in f:
                    path = os.path.join(root, f)
                    files_tmp.append(path)
        return files_tmp

    def remove_files_tmp(check=False):
        shutil.rmtree(dir_tmp)
        files_tmp = find_files_tmp()
        if files_tmp:
            print(f"Removing {files_tmp}")
            for f in files_tmp:
                os.remove(f)
        if check:
            files_tmp = find_files_tmp()
            if files_tmp:
                raise RuntimeError(
                    f"Expected temporary files to be gone but still have {files_tmp}"
                )

    remove_files_tmp(check=True)

    for dir_fire in tqdm(dirs_fire, desc="Copying interim"):
        probs, interim = find_outputs(dir_fire)
        if probs:
            # already have final outputs so leave alone
            continue
        if not interim:
            logging.info(f"No interim outputs yet for {dir_fire}")
            continue
        dir_tmp_fire = os.path.join(dir_tmp, os.path.basename(dir_fire))
        shutil.copytree(dir_fire, dir_tmp_fire)
        # double check that outputs weren't created while copying
        probs, interim = find_outputs(dir_tmp_fire)
        if probs:
            continue
        for f in tqdm(interim):
            f_interim = os.path.join(dir_tmp_fire, f)
            f_tmp = f_interim.replace("interim_", "")
            shutil.move(f_interim, f_tmp)
        probs, interim = find_outputs(dir_tmp_fire)
        if interim:
            raise RuntimeError("Expected files to be renamed")
        copy_fire_outputs(dir_tmp_fire, dir_output, changed=True, suffix=TMP_SUFFIX)


def publish_all(
    dir_output=None,
    changed_only=True,
    force=False,
    force_project=False,
    include_interim=None,
):
    dir_output = find_latest_outputs(dir_output)
    check_copy_interim(dir_output, include_interim)
    changed = merge_dirs(
        dir_output, changed_only=changed_only, force=force, force_project=force_project
    )
    if changed or force:
        import publish_azure

        publish_azure.upload_dir(dir_output)
        # HACK: might be my imagination, but maybe there's a delay so wait a bit
        time.sleep(PUBLISH_AZURE_WAIT_TIME_SECONDS)
        import publish_geoserver

        publish_geoserver.publish_folder(dir_output)


def find_latest_outputs(dir_output=None):
    if dir_output is None:
        dir_default = DIR_OUTPUT
        dirs_with_initial = [
            x
            for x in list_dirs(dir_default)
            if os.path.isdir(os.path.join(dir_default, x, "initial"))
        ]
        if dirs_with_initial:
            dir_output = os.path.join(dir_default, dirs_with_initial[-1])
            logging.info("Defaulting to directory %s", dir_output)
            return dir_output
        else:
            raise RuntimeError(
                f'find_latest_outputs("{dir_output}") failed: No run found'
            )
    return dir_output


def merge_dirs(
    dir_input=None,
    changed_only=True,
    force=False,
    force_project=False,
    creation_options=CREATION_OPTIONS,
    check_valid=True,
):
    any_change = False
    dir_input = find_latest_outputs(dir_input)
    # expecting dir_input to be a path ending in a runid of form '%Y%m%d%H%M'
    dir_base = os.path.join(dir_input, "initial")
    if not os.path.isdir(dir_base):
        raise RuntimeError(f"Directory {dir_base} missing")
    run_name = os.path.basename(dir_input)
    run_id = run_name[run_name.index("_") + 1 :]
    logging.info("Merging {}".format(dir_base))
    co = list(
        itertools.chain.from_iterable(map(lambda x: ["-co", x], creation_options))
    )
    dir_parent = os.path.dirname(dir_base)
    # want to put probability and perims together
    dir_out = ensure_dir(os.path.join(dir_parent, "combined"))
    files_by_for_what = {}
    for for_what in list_dirs(dir_base):
        dir_for_what = os.path.join(dir_base, for_what)
        files_by_for_what[for_what] = files_by_for_what.get(for_what, []) + [
            os.path.join(dir_for_what, x)
            for x in listdir_sorted(dir_for_what)
            if x.endswith(".tif")
        ]
    dirs_what = [os.path.basename(for_what) for for_what in files_by_for_what.keys()]
    for_dates = [
        datetime.datetime.strptime(_, FMT_DATE_YMD) for _ in dirs_what if "perim" != _
    ]
    date_origin = min(for_dates)
    for for_what, files in tqdm(
        files_by_for_what.items(), desc=f"Merging {dir_parent}"
    ):
        files = files_by_for_what[for_what]
        dir_in_for_what = os.path.basename(for_what)
        # HACK: forget about tiling and just do what we need now
        if "perim" == dir_in_for_what:
            dir_for_what = "perim"
            date_cur = for_dates[0]
            description = "perimeter"
        else:
            date_cur = datetime.datetime.strptime(dir_in_for_what, FMT_DATE_YMD)
            offset = (date_cur - date_origin).days + 1
            dir_for_what = f"day_{offset:02d}"
            description = "probability"
        dir_crs = ensure_dir(os.path.join(dir_parent, "reprojected", dir_in_for_what))

        def reproject(f):
            changed = False
            f_crs = os.path.join(dir_crs, os.path.basename(f))
            # don't project if file already exists, but keep track of file for merge
            if force_project or not os.path.isfile(f_crs):
                # FIX: this is super slow for perim tifs
                #       (because they're the full extent of the UTM zone?)
                b = project_raster(
                    f,
                    f_crs,
                    resolution=100,
                    nodata=0,
                    crs=f"EPSG:{CRS_COMPARISON}",
                )
                if b is None:
                    return b
                changed = True
            return changed, f_crs

        results_crs = [
            reproject(f)
            for f in tqdm(files, desc=f"Reprojecting for {dir_in_for_what}")
        ]
        results_crs = [x for x in results_crs if x is not None]
        files_crs = [x[1] for x in results_crs]
        files_crs_changed = [x[1] for x in results_crs if x[0]]
        changed = 0 < len(files_crs_changed)
        file_root = os.path.join(
            dir_out, f"firestarr_{run_id}_{dir_for_what}_{date_cur.strftime('%Y%m%d')}"
        )
        file_tmp = f"{file_root}_tmp.tif"
        file_base = f"{file_root}.tif"
        # argv = (["", "-a_nodata", "-1"]
        #     + co
        #     + ["-o", file_tmp]
        #     + files_crs)
        # no point in doing this if nothing was added
        if force or changed or not os.path.isfile(file_base):
            if os.path.isfile(file_tmp):
                os.remove(file_tmp)

            def do_merge(file_merge):
                # HACK: seems like currently making empty combined raster so delete
                #       first in case it's merging into existing and causing problems
                if changed_only and os.path.isfile(file_base):
                    files_merge = files_crs_changed + [file_base]
                else:
                    files_merge = files_crs
                if check_valid:
                    files_invalid = find_invalid_tiffs(files_merge)
                    if files_invalid:
                        logging.error(f"Ignoring invalid files:\n\t{files_invalid}")
                        files_merge = [x for x in files_merge if x not in files_invalid]
                if 0 == len(files_merge):
                    logging.error("No files to merge")
                    return None

                @ensures(
                    paths=file_merge,
                    remove_on_exception=True,
                    retries=NUM_RETRIES,
                )
                def do_actual_merge(_):
                    if 1 == len(files_merge):
                        f = files_merge[0]
                        if f == _:
                            logging.warning(
                                f"Ignoring trying to merge file into iteslf: {f}"
                            )
                        else:
                            logging.warning(
                                f"Only have one file so just copying {f} to {_}"
                            )
                            shutil.copy(f, _)
                        return _
                    merge_safe(
                        (
                            [
                                "",
                                # "-n", "0",
                                "-a_nodata",
                                "-1",
                                "-d",
                                description,
                            ]
                            + co
                            + ["-o", file_tmp]
                            + files_merge
                        )
                    )

                return do_actual_merge(file_merge)

            file_tmp = do_merge(file_tmp)
            if not find_invalid_tiffs(file_tmp):
                if os.path.isfile(file_base):
                    os.remove(file_base)
                if "GTiff" == FORMAT_OUTPUT:
                    shutil.move(file_tmp, file_base)
                else:
                    # HACK: reproject should basically just be copy?
                    # convert to COG
                    project_raster(
                        file_tmp,
                        file_base,
                        nodata=-1,
                        resolution=100,
                        format=FORMAT_OUTPUT,
                        crs=f"EPSG:{CRS_COMPARISON}",
                        options=creation_options
                        + [
                            # shouldn't need much precision just for web display
                            "NBITS=16",
                            # shouldn't need alpha?
                            # "ADD_ALPHA=NO",
                            # "SPARSE_OK=TRUE",
                            "PREDICTOR=YES",
                        ],
                    )
                    os.remove(file_tmp)
                changed = True
            any_change = any_change or changed
        else:
            logging.info(f"Output already exists for {file_base}")

    logging.info("Final results of merge are in %s", dir_out)
    try:
        run_id = os.path.basename(dir_input)
        file_zip = os.path.join(DIR_ZIP, f"{run_name}.zip")
        if any_change or not os.path.isfile(file_zip):
            logging.info("Creating archive %s", file_zip)
            zip_folder(file_zip, dir_out)
    except KeyboardInterrupt as ex:
        raise ex
    except Exception as ex:
        logging.error("Ignoring zip error")
        logging.error(get_stack(ex))

    return any_change
