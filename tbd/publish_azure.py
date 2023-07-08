import sys
sys.path.append('../util')
from common import *

import os
import datetime
import urllib.parse

DIR_ROOT = "/appl/data/output"


from azure.storage.blob import BlobClient
from azure.storage.blob import BlobServiceClient
from azure.storage.blob import ExponentialRetry
from azure.storage.blob import ContainerClient


AZURE_URL = None
AZURE_TOKEN = None
AZURE_CONTAINER = None

def get_token():
    # HACK: % in config file gets parsed as variable replacement, so unqoute for that
    token = CONFIG.get('azure', 'token')
    args = token.split('&')
    args_kv = {k: v for k, v in [(arg[:arg.index('=')], arg[(arg.index('=') + 1):]) for arg in args]}
    args_kv['sig'] = urllib.parse.quote(args_kv['sig'])
    return '&'.join(f"{k}={v}" for k, v in args_kv.items())


def read_config():
    global AZURE_URL
    global AZURE_TOKEN
    global AZURE_CONTAINER
    try:
        AZURE_URL = CONFIG.get('azure', 'url')
        AZURE_TOKEN = get_token()
        AZURE_CONTAINER = CONFIG.get('azure', 'container')
    except ValueError as ex:
        logging.error(ex)
        logging.warning("Unable to read azure config")
    return (AZURE_URL and AZURE_TOKEN and AZURE_CONTAINER)

def get_blob_service_client():
    retry = ExponentialRetry(initial_backoff=1, increment_base=3, retry_total=5)
    return BlobServiceClient(
        account_url=AZURE_URL,
        credential=AZURE_TOKEN,
        retry_policy=retry
    )

def get_container():
    blob_service_client = get_blob_service_client()
    container = blob_service_client.get_container_client(AZURE_CONTAINER)
    return container


def show_blobs(container):
    blob_list = [x for x in container.list_blobs()]
    # blob_list = container.list_blobs()
    for blob in blob_list:
        print(f"{container.container_name}: {blob.name}")



# def archive_current(container):
#     # should ignore archive folder
#     blob_list = [x for x in container.list_blobs(name_starts_with="firestarr")]
#     # blob_list = container.list_blobs()
#     for blob in blob_list:
#         print(f"{container.container_name}: {blob.name}")

# blob_service_client = get_blob_service_client()
# blob_client = blob_service_client.get_blob_client(AZURE_CONTAINER, blob.name)
# new_blob_client = blob_service_client.get_blob_client(AZURE_CONTAINER, f"archive/{blob.name}")
# new_blob_client.start_copy_from_url(blob_client.url)

# # Delete the original blob
# blob_client.delete_blob()
# print("The blob is Renamed successfully:",{new_blob_name})



def upload_dir(dir_run):
    if not read_config():
        return False
    run_id = os.path.basename(dir_run)
    container = None
    dir_combined = os.path.join(dir_run, "combined")
    dates = os.listdir(dir_combined)
    source = os.path.basename(os.path.dirname(dir_run))
    assert (1 == len(dates))
    for date in dates:
        dir_date = os.path.join(dir_combined, date)
        files = os.listdir(dir_date)
        # HACK: ignore perim for now
        files = [f for f in files if 'perim' not in f]
        # assert ('perim.tif' in files)
        def get_day(f):
            i = f.rindex("_")
            n = int(f[(f[:i].rindex('_') + 1): i])
            return n
        days = {f: get_day(f) for f in files if f != 'perim.tif'}
        run_length = max(days.values())
        metadata = {
            "model": "firestarr",
            "run_id": run_id,
            "source": source,
            "run_length": f"{run_length}",
            "origin_date": date,
        }
        origin = datetime.datetime.strptime(date, "%Y%m%d").date()
        if container is None:
            # wait until we know we need it
            container = get_container()
        # delete old blobs
        blob_list = [x for x in container.list_blobs(name_starts_with="current/firestarr")]
        for blob in blob_list:
            container.delete_blob(blob.name)
        # archive_current(container)
        for f in files:
            if 'perim.tif' == f:
                for_date = origin
            else:
                for_date = origin + datetime.timedelta(days=(days[f] - 1))
            metadata['for_date'] = for_date.strftime('%Y%m%d')
            path = os.path.join(dir_date, f)
            # HACK: just upload into archive too so we don't have to move later
            with open(path, "rb") as data:
                container.upload_blob(
                    name=f"current/{f}",
                    data=data,
                    metadata=metadata,
                    overwrite=True
                )
            archived = f"archive/{f}"
            if 0 == len([x for x in container.list_blobs(archived)]):
                # don't upload if already in archive
                with open(path, "rb") as data:
                    container.upload_blob(
                        name=archived,
                        data=data,
                        metadata=metadata,
                        overwrite=True
                    )


def upload_from_zip(z):
    dir_main = os.path.dirname(z)
    run_id = z[(z.rindex('_') + 1):z.rindex('.')]
    dir_run = os.path.join(dir_main, run_id)
    if os.path.isdir(dir_run):
        upload_dir(dir_run)


def upload_from_zips(source="current_m3"):
    dir_main = os.path.join(DIR_ROOT, source)
    zips = [x for x in os.listdir(dir_main) if x.endswith('.zip')]
    for z in zips:
        upload_from_zip(os.path.join(dir_main, z))


def upload_latest(source="current_m3"):
    dir_main = os.path.join(DIR_ROOT, source)
    zips = [x for x in os.listdir(dir_main) if x.endswith('.zip')]
    upload_from_zip(os.path.join(dir_main, zips[-1]))


if "__main__" == __name__:
    upload_latest()
