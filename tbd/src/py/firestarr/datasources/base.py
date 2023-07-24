from datasources.datatypes import check_columns
import datasources.spotwx
from gis import make_empty_gdf


class SourceSelector(object):
    def __init__(self) -> None:
        self._bounds = make_empty_gdf(["ID", "PRIORITY"])
        self._sources = {
            "fire": [],
            "model": [],
            "hourly": [],
            "fwi": [],
        }
        self._sources["model"].append(datasources.spotwx.SourceGEPS())

    def register(self, source):
        if source.provides not in self._sources.keys():
            raise NotImplementedError("Invalid data source type")
        self._sources[source.provides].append(source)

    def get_fires(self):
        # fires is just the base one and then replace everything that another
        # source provides
        # df_fires = []
        # for source in self._sources["fire"]:
        #     df = source.get_fires()
        pass

    def get_wx_model(self, lat, lon):
        return self._sources["model"][0].get_wx_forecast(lat, lon)

    def get_fwi(self, lat, lon, date):
        return check_columns(self._get_fwi(lat, lon, date), "fwi")

    def get_wx_hourly(self, lat, lon, date):
        return check_columns(self._get_wx_hourly(lat, lon, date), "weather")
