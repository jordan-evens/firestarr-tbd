import rasterio
from rasterio.plot import show

fp = r'../FireSTARR/data/output.release/probability_252_2017-09-09.tif'
CMD = [
    'wsl',
   'bash',
    '-c',
   'DOCKER_HOST="unix:///mnt/wsl/shared-docker/docker.sock" /usr/bin/docker-compose exec firestarr cmake-build-release/FireSTARR ./Data/output.release 2017-08-27 52.01 -89.024 12:15 --wx test/wx.csv --ffmc 90 --dmc 40 --dc 300 --apcp_0800 0 --no-intensity -v -v'
]
# This is a sample Python script.

# Press Shift+F10 to execute it or replace it with your code.
# Press Double Shift to search everywhere for classes, files, tool windows, actions, and settings.

# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    pass

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
import numpy as np
import rasterio
from rasterio import features
from rasterio.mask import mask

import subprocess
subprocess.run(CMD)

# the first one is your raster on the right
# and the second one your red raster
with rasterio.open(fp) as src:
    src_affine = src.meta.get("transform")

    # Read the first band of the "mask" raster
    band = src.read(1)
    # Use the same value on each pixel with data
    # in order to speedup the vectorization
    band[np.where(band != src.nodata)] = 1

    geoms = []
    for geometry, raster_value in features.shapes(band, transform=src_affine):
        # get the shape of the part of the raster
        # not containing "nodata"
        if raster_value == 1:
            geoms.append(geometry)

    # crop the second raster using the
    # previously computed shapes
    out_img, out_transform = mask(
        dataset=src,
        shapes=geoms,
        crop=True,
    )

    # save the result
    # (don't forget to set the appropriate metadata)
    with rasterio.open(
        'result.tif',
        'w',
        driver='GTiff',
        height=out_img.shape[1],
        width=out_img.shape[2],
        count=src.count,
        dtype=out_img.dtype,
        transform=out_transform,
        nodata=src.nodata
    ) as dst:
        dst.write(out_img)

    img = rasterio.open('result.tif')
    show(img)