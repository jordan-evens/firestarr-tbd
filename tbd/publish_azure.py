import os
import sys
sys.path.append('../util')
import common
import datetime
import urllib.parse

DIR_ROOT = "/appl/data/output"


from azure.storage.blob import BlobClient
from azure.storage.blob import BlobServiceClient
from azure.storage.blob import ContainerClient



def get_token():
    # HACK: % in config file gets parsed as variable replacement, so unqoute for that
    token = common.CONFIG.get('azure', 'token')
    args = token.split('&')
    args_kv = {k: v for k, v in [(arg[:arg.index('=')], arg[(arg.index('=') + 1):]) for arg in args]}
    args_kv['sig'] = urllib.parse.quote(args_kv['sig'])
    return '&'.join(f"{k}={v}" for k, v in args_kv.items())


AZURE_URL = common.CONFIG.get('azure', 'url')
AZURE_TOKEN = get_token()
AZURE_CONTAINER = common.CONFIG.get('azure', 'container')

def get_container():
    blob_service_client = BlobServiceClient(
        account_url=AZURE_URL,
        credential=AZURE_TOKEN
    )
    container = blob_service_client.get_container_client(AZURE_CONTAINER)
    return container


def show_blobs(container):
    blob_list = [x for x in container.list_blobs()]
    # blob_list = container.list_blobs()
    for blob in blob_list:
        print(f"{container.name}: {blob.name}")


def upload_dir(dir_run)
    container = None
    dir_combined = os.path.join(dir_run, "combined")
    dates = os.listdir(dir_combined)
    assert (1 == len(dates))
    for dir_date in dates:
        dir_rasters = os.path.join(dir_combined, dir_date, "rasters")
        files = os.listdir(dir_rasters)
        assert ('perim.tif' in files)
        days = {f: int(f[(f.rindex('_') + 1): f.rindex('.')]) for f in files if f != 'perim.tif'}
        run_length = max(days.values())
        metadata = {
            "model": "firestarr",
            "run_id": run_id,
            "source": source,
            "run_length": f"{run_length}",
            "origin_date": dir_date,
        }
        origin = datetime.datetime.strptime(dir_date, "%Y%m%d").date()
        if container is None:
            # wait until we know we need it
            container = get_container()
        for f in files:
            if 'perim.tif' == f:
                for_date = origin
            else:
                for_date = origin + datetime.timedelta(days=(days[f] - 1))
            metadata['for_date'] = for_date.strftime('%Y%m%d')
            path = os.path.join(dir_rasters, f)
            with open(path, "rb") as data:
                container.upload_blob(
                    name=f,
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
