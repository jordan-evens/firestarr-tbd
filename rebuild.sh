#############  setup commands
git pull
mkdir -p data/generated/tiled
mkdir -p data/wx/longrange
chmod +x GIS/init.sh

docker-compose stop
docker-compose rm -f
docker-compose build --parallel
docker-compose up -d
# needs to run once to make tbd grids
docker-compose run --rm gis ./init.sh


#############  gis python container
# docker-compose run --rm gis /bin/bash

#############  tbd cli
# docker-compose run --rm tbd /bin/bash

#############  test tbd
# docker-compose run --rm tbd ./TBD ./Data/output 2017-08-27 52.01 -89.024 12:15 -v --wx Data/output/wx.csv --ffmc 90 --dmc 40 --dc 300 --apcp_0800 0
