#############  setup commands
git pull
mkdir -p data/generated/grid
chmod +x gis/init.sh

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
# docker-compose run --rm tbd ./tbd ./data/output 2017-08-27 52.01 -89.024 12:15 -v --wx data/output/wx.csv --ffmc 90 --dmc 40 --dc 300 --apcp_0800 0
