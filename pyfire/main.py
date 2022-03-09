import os

fp = r'../FireSTARR/{}/probability_252_2017-09-09.tif'.format(dir_out)

# See PyCharm help at https://www.jetbrains.com/help/pycharm/
import numpy as np
import rasterio
from rasterio import features
from rasterio.mask import mask

import subprocess


import tkinter as tk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from matplotlib.backends.backend_tkagg import (
    FigureCanvasTkAgg, NavigationToolbar2Tk)
# Implement the default Matplotlib key bindings.
from matplotlib.backend_bases import key_press_handler
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

root = tk.Tk()

fig = Figure(figsize=(5, 4), dpi=100)

canvas1 = FigureCanvasTkAgg(fig, master=root)
canvas1.draw()

toolbar = NavigationToolbar2Tk(canvas1,root)
toolbar.update()
toolbar.pack(side=tkinter.TOP, fill=tkinter.X, padx=8)

canvas1.get_tk_widget().pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=1, padx=0, pady=0)

canvas1._tkcanvas.pack(side=tkinter.TOP, fill=tkinter.BOTH, expand=1, padx=0, pady=0)


def add_entry(name, value, upper, lower=0):
    label = tk.Label(text=name)
    entry = tk.Spinbox(root, from_=lower, to=upper)
    entry.delete(0)
    entry.insert(0, str(value))
    label.pack(side="left")
    entry.pack(side="left")
    return label, entry


lblFFMC, inputFFMC = add_entry("FFMC", 90, upper=101)
lblDMC, inputDMC = add_entry("DMC", 40, upper=1000)
lblDC, inputDC = add_entry("DC", 300, upper=10000)
lblAPCP, inputAPCP = add_entry("APCP", 0, upper=1000)

btnRun = tk.Button(text="Run")
btnRun.pack()


def handle_click(event):
    print("Running...")
    do_it()

btnRun.bind("<Button-1>", handle_click)

def do_it():
    dir_out = 'Data/output.release'
    ffmc = float(inputFFMC.get())
    dmc = float(inputDMC.get())
    dc = float(inputDC.get())
    apcp_0800 = float(inputAPCP.get())
    args = './{} 2017-08-27 52.01 -89.024 12:15 --wx test/wx.csv --ffmc {} --dmc {} --dc {} --apcp_0800 {} --no-intensity -v -v'.format(
        dir_out, ffmc, dmc, dc, apcp_0800)
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

        import rasterio as rio
        from rasterio.plot import show
        ax = fig.add_subplot(111)
        fig.subplots_adjust(bottom=0, right=1, top=1, left=0, wspace=0, hspace=0)

        #    fig.tight_layout(pad=0)

        with rio.open(file_out) as src_plot:
            show(src_plot, ax=ax, cmap='gist_gray')
        plt.close()
        ax.set(title="", xticks=[], yticks=[])
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        canvas1.draw()

root.mainloop()
