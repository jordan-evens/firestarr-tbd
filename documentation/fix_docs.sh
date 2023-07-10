#!/bin/bash
cp -r ../img ./html/
cd ./html
sed -i 's/\(.*id\="autotoc_md2".*\)/<h3>Other documentation<\/h3>\n\1/g' index.html
sed -i 's/\(.*id\="autotoc_md2".*\)/<ul><li><a href="firestarr\/index.html">Spread algorithm<\/a><\/li><\/ul>\n\1/g' index.html
sed -i 's/\(.*id\="autotoc_md2".*\)/<ul><li><a href="gis\/index.html">Raster creation scripts<\/a><\/li><\/ul>\n\1/g' index.html
