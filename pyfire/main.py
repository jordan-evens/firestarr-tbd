import os

fp = r'../FireSTARR/{}/probability_252_2017-09-09.tif'.format(dir_out)

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
import numpy as np
import rasterio
from rasterio import features
from rasterio.mask import mask
import rasterio as rio
from rasterio.plot import show

import subprocess

import tkinter as tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk)
# Implement the default Matplotlib key bindings.
from matplotlib.backend_bases import key_press_handler
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

ax = None
root = tk.Tk()
frmMap = tk.Frame()
frmLocation = tk.Frame()
frmFWI = tk.Frame()
fig = Figure(figsize=(5, 4), dpi=100)

canvas1 = FigureCanvasTkAgg(fig, master=frmMap)
canvas1.draw()

toolbar = NavigationToolbar2Tk(canvas1, frmMap)
toolbar.update()
toolbar.pack(side=tk.TOP, fill=tk.X, padx=8)

canvas1.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1, padx=0, pady=0)

canvas1._tkcanvas.pack(side=tk.TOP, fill=tk.BOTH, expand=1, padx=0, pady=0)

frmMap.pack(fill=tk.BOTH, expand=1)


def add_entry(master, name, value, upper, lower=0, increment=1):
    var = tk.StringVar()
    var.set(str(value))
    label = tk.Label(master, text=name)
    entry = tk.Spinbox(master, from_=lower, to=upper, textvariable=var, increment=increment)
    label.pack(side="left")
    entry.pack(side="left")
    return label, entry, var

lblLat, inputLat, varLat = add_entry(frmLocation, "Latitude", 52.01, upper=90, lower=-90, increment=0.001)
lblLon, inputLon, varLon = add_entry(frmLocation, "Longitude", -89.024, upper=180, lower=-180, increment=0.001)
frmLocation.pack()

lblFFMC, inputFFMC, varFFMC = add_entry(frmFWI, "FFMC", 90, upper=101, increment=0.1)
lblDMC, inputDMC, varDMC = add_entry(frmFWI, "DMC", 40, upper=1000)
lblDC, inputDC, varDC = add_entry(frmFWI, "DC", 300, upper=10000)
lblAPCP, inputAPCP, varAPCP = add_entry(frmFWI, "APCP", 0, upper=1000, increment=0.1)

frmFWI.pack()
btnRun = tk.Button(text="Run")
btnRun.pack(side="bottom")


def handle_click(event):
    print("Running...")
    do_it()


btnRun.bind("<Button-1>", handle_click)


def do_it():
    global ax
    global fig
    dir_out = 'Data/output.release'
    ffmc = float(varFFMC.get())
    dmc = float(varDMC.get())
    dc = float(varDC.get())
    apcp_0800 = float(varAPCP.get())
    lat = float(varLat.get())
    lon = float(varLon.get())
    args = './{} 2017-08-27 {} {} 12:15 --wx test/wx.csv --ffmc {} --dmc {} --dc {} --apcp_0800 {} --no-intensity -v -v'.format(
        dir_out, lat, lon, ffmc, dmc, dc, apcp_0800)
    cmd = [
        'wsl',
        'bash',
        '-c',
        'DOCKER_HOST="unix:///mnt/wsl/shared-docker/docker.sock" /usr/bin/docker-compose exec firestarr cmake-build-release/FireSTARR {}'.format(
            args)
    ]
    subprocess.run(cmd)

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
        file_out = 'result.tif'
        if os.path.exists(file_out):
            os.remove(file_out)
        # save the result
        # (don't forget to set the appropriate metadata)
        with rasterio.open(
                file_out,
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
        fig.clf()
        if ax is not None:
            ax.cla()
        ax = fig.add_subplot(111)
        fig.subplots_adjust(bottom=0, right=1, top=1, left=0, wspace=0, hspace=0)
        with rio.open(file_out) as src_plot:
            show(src_plot, ax=ax, cmap='Oranges')
        plt.close()
        ax.set(title="", xticks=[], yticks=[])
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        canvas1.draw()


root.mainloop()
