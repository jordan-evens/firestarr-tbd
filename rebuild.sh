#############  setup commands
git pull
chmod +x gis/init.sh

docker-compose stop
docker-compose rm -f
docker-compose build
docker-compose up -d


# If you want to run the grid creation manually then comment this out and uncomment the ./init.sh call
if [ ! -f "data/generated/grid/grids.tar" ]
then
  cd data/generated/grid/
  wget -c --no-check-certificate https://cromulentcreations.ca/tbd/grids.tar
  tar xvf grids.tar
fi
# needs to run once to make grids
# docker-compose run --rm gis ./init.sh


#############  gis python container
# docker-compose run --rm gis /bin/bash

#############  tbd cli
# docker-compose run --rm tbd /bin/bash

#############  test tbd
# docker-compose run --rm tbd ./tbd ./data/output 2017-08-27 52.01 -89.024 12:15 -v --wx data/output/wx.csv --ffmc 90 --dmc 40 --dc 300 --apcp_0800 0
