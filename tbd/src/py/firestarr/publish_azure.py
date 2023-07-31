import datetime
import os
import urllib.parse

import numpy as np
import pandas as pd
from azure.storage.blob import BlobServiceClient, ExponentialRetry
from common import (
    CONFIG,
    DIR_OUTPUT,
    DIR_ZIP,
    FMT_DATE_YMD,
    is_empty,
    listdir_sorted,
    logging,
)

AZURE_URL = None
AZURE_TOKEN = None
AZURE_CONTAINER = None


def get_token():
    # HACK: % in config file gets parsed as variable replacement, so unqoute for that
    token = CONFIG.get("AZURE_TOKEN", "")
    args = token.split("&")
    args_kv = {
        k: v
        for k, v in [
            (arg[: arg.index("=")], arg[(arg.index("=") + 1) :]) for arg in args
        ]
    }
    args_kv["sig"] = urllib.parse.quote(args_kv["sig"])
    return "&".join(f"{k}={v}" for k, v in args_kv.items())


def read_config():
    global AZURE_URL
    global AZURE_TOKEN
    global AZURE_CONTAINER
    try:
        AZURE_URL = CONFIG.get("AZURE_URL", "")
        AZURE_TOKEN = get_token()
        AZURE_CONTAINER = CONFIG.get("AZURE_CONTAINER", "")
    except ValueError as ex:
        logging.error(ex)
        logging.warning("Unable to read azure config")
    return np.all(bool(x) for x in [AZURE_URL, AZURE_TOKEN, AZURE_CONTAINER])


def get_blob_service_client():
    retry = ExponentialRetry(initial_backoff=1, increment_base=3, retry_total=5)
    return BlobServiceClient(
        account_url=AZURE_URL, credential=AZURE_TOKEN, retry_policy=retry
    )


def get_container():
    logging.info("Getting container")
    blob_service_client = get_blob_service_client()
    container = blob_service_client.get_container_client(AZURE_CONTAINER)
    return container


def show_blobs(container):
    blob_list = [x for x in container.list_blobs()]
    # blob_list = container.list_blobs()
    for blob in blob_list:
        print(f"{container.container_name}: {blob.name}")


def find_latest():
    zips = [x for x in listdir_sorted(DIR_ZIP) if x.endswith(".zip")]
    return os.path.join(DIR_OUTPUT, os.path.splitext(zips[-1])[0])


def upload_dir(dir_run=None):
    if not read_config():
        logging.info(f"Azure not configured so not publishing {dir_run}")
        return False
    if dir_run is None:
        dir_run = find_latest()
    logging.info(f"Azure configured so publishing {dir_run}")
    run_name = os.path.basename(dir_run)
    run_id = run_name[run_name.index("_") + 1 :]
    source = run_name[: run_name.index("_")]
    date = pd.to_datetime(run_id).date().strftime(FMT_DATE_YMD)
    container = None
    dir_combined = os.path.join(dir_run, "combined")
    files = listdir_sorted(dir_combined)
    # HACK: ignore perim for now
    files = [f for f in files if "perim" not in f]

    # assert ('perim.tif' in files)
    def get_day(f):
        i = f.rindex("_")
        n = int(f[(f[:i].rindex("_") + 1) : i])
        return n

    days = {f: get_day(f) for f in files if f != "perim.tif"}
    run_length = max(days.values())
    metadata = {
        "model": "firestarr",
        "run_id": run_id,
        "run_length": f"{run_length}",
        "source": source,
        "origin_date": date,
    }
    origin = datetime.datetime.strptime(date, FMT_DATE_YMD).date()
    if container is None:
        # wait until we know we need it
        container = get_container()
    logging.info("Listing blobs")
    # delete old blobs
    blob_list = [x for x in container.list_blobs(name_starts_with="current/firestarr")]
    for blob in blob_list:
        logging.info(f"Deleting {blob.name}")
        container.delete_blob(blob.name)
    # archive_current(container)
    for f in files:
        logging.info(f"Pushing {f}")
        if "perim.tif" == f:
            for_date = origin
        else:
            for_date = origin + datetime.timedelta(days=(days[f] - 1))
        metadata["for_date"] = for_date.strftime(FMT_DATE_YMD)
        path = os.path.join(dir_combined, f)
        # HACK: just upload into archive too so we don't have to move later
        with open(path, "rb") as data:
            container.upload_blob(
                name=f"current/{f}", data=data, metadata=metadata, overwrite=True
            )
        archived = f"archive/{f}"
        if is_empty([x for x in container.list_blobs(archived)]):
            # don't upload if already in archive
            with open(path, "rb") as data:
                container.upload_blob(
                    name=archived, data=data, metadata=metadata, overwrite=True
                )


if "__main__" == __name__:
    upload_dir()
