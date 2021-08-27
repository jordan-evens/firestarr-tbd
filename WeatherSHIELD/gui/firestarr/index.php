<!DOCTYPE html>
<html>

<head>
    <title>FireSTARR Outputs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    <link rel="stylesheet" href="dist/leaflet.css" />
    <link rel="stylesheet" href="examples.css" />

    <link href="https://fonts.googleapis.com/css?family=Roboto:100,400" rel="stylesheet">
</head>

<body>
    <h1 class="title mapTitle">FireSTARR Outputs</h1>
    <div id="map"></div>

    <!-- CDN -->
    <script src="//d3js.org/d3.v4.min.js"></script>
    <script src="//npmcdn.com/leaflet@1.2.0/dist/leaflet.js"></script>
    <script src="//npmcdn.com/geotiff@0.3.6/dist/geotiff.js"></script>
    <script src="//cdnjs.cloudflare.com/ajax/libs/chroma-js/2.1.0/chroma.min.js"></script>

    <!-- Plugin -->
    <script src="https://ihcantabria.github.io/Leaflet.CanvasLayer.Field/dist/leaflet.canvaslayer.field.js"></script>

    <script>
        let map = L.map('map');
        let perim_file = '/data/output/perimeter.tif';
        let prob_file = '/data/output/probability.tif';
        /* Dark basemap */
        let url = 'https://cartodb-basemaps-{s}.global.ssl.fastly.net/dark_nolabels/{z}/{x}/{y}.png';
        L.tileLayer(url, {
            attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd'
        }).addTo(map);
      
        // d3.request(perim_file).responseType('arraybuffer').get(
          // function (error, tiffData) {
            // let geo = L.ScalarField.fromGeoTIFF(tiffData.response, bandIndex = 0);
            // let layerPerim = L.canvasLayer.scalarField(geo, {
              // color: chroma.scale('RdPu').domain(geo.range),
              // opacity: 0.65
            // }).addTo(map);
            d3.request(prob_file).responseType('arraybuffer').get(
              function (error, tiffData) {
                let geo = L.ScalarField.fromGeoTIFF(tiffData.response, bandIndex = 0);

                let layerProb = L.canvasLayer.scalarField(geo, {
                  color: chroma.scale(['#9fd0e3', '#faf68e', '#fcdf4c', '#fac043', '#f5a23d', '#f28938', '#f06b32', '#ed4e2b', '#eb3326', '#e6151f']).domain([0,1]),
                  opacity: 1.0
                }).addTo(map);
                layerProb.on('click', function (e) {
                if (e.value !== null) {
                  let v = (100 * e.value).toFixed(0);
                  let html = (`<span class="popupText">Probability ${v}%</span>`);
                  let popup = L.popup()
                              .setLatLng(e.latlng)
                              .setContent(html)
                              .openOn(map);
                  }
                });

                L.control.layers({
                  // "Perimeter": layerPerim,
                  "Probability": layerProb,
                }, {}, {
                position: 'bottomleft',
                collapsed: false
              }).addTo(map);
              map.fitBounds(layerProb.getBounds());
          });
      // });
        
    </script>
</body>

</html>

