#!/bin/bash

python collect.py
python earthenv.py
cd canvec
python canvec.py extract Hydro
cd ..
python make_grids.py
