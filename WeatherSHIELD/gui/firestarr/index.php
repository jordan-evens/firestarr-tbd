<!DOCTYPE html>
<html>

<head>
    <title>FireSTARR Outputs</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
    <link rel="stylesheet" href="//npmcdn.com/leaflet@1.2.0/dist/leaflet.css" />
    <link rel="stylesheet" href="https://ihcantabria.github.io/Leaflet.CanvasLayer.Field/examples.css" />

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
<?php
$ROOT_DIR = '/app/data/output/';
$PERIM_DIR = $ROOT_DIR.'perimeter/';
$PROB_DIR = $ROOT_DIR.'probability/';
function listdir($dir)
{
  $SEP = '';
  $EOL = "\n";
  $result = '';
  foreach(scandir($dir) as $file) {
    if ($file != '.' && $file != '..')
    {
      $result = $result.$SEP."'".substr($dir, 4).$file."'";
      $SEP = ', ';
    }
  }
  return $result;
}
echo 'let perim_files = ['.listdir($PERIM_DIR.'tiled/')."];\n";
echo 'let prob_files = ['.listdir($PROB_DIR.'tiled/')."];\n";
?>
// perim_files = perim_files.slice(-1);
// prob_files = prob_files.slice(-1);
        /* Dark basemap */
        let url = 'https://cartodb-basemaps-{s}.global.ssl.fastly.net/dark_nolabels/{z}/{x}/{y}.png';
        L.tileLayer(url, {
            attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, &copy; <a href="https://carto.com/attributions">CARTO</a>',
            subdomains: 'abcd'
        }).addTo(map);
        let perims = [];
        let probs = [];
        let expected_perims = perim_files.length;
        let expected_probs = prob_files.length;
        function addPerim(i)
        {
          if (i == perim_files.length)
          {
            //setTimeout(function() { return addPerim(0); }, 0);
            return;
          }
          // setTimeout(function() { return addPerim(i + 1); }, 0);
          file = perim_files[i];
          d3.request(file).responseType('arraybuffer').get(
            function (error, tiffData) {
              try {
                let geo = L.ScalarField.fromGeoTIFF(tiffData.response, bandIndex = 0);
                let layerPerim = L.canvasLayer.scalarField(geo, {
                  color: chroma.scale('RdPu').domain(geo.range),
                  opacity: 0.65,
                  inFilter: (v) => v !== 0
                });
                perims.push(layerPerim);
              } catch(err) {
                expected_perims--;
              }
            });
        }
        function addProb(i)
        {
          if (i == prob_files.length)
          {
            return;
          }
          // setTimeout(function() { return addProb(i + 1); }, 0);
          file = prob_files[i];
          d3.request(file).responseType('arraybuffer').get(
          function (error, tiffData) {
            try {
              let geo = L.ScalarField.fromGeoTIFF(tiffData.response, bandIndex = 0);

              let layerProb = L.canvasLayer.scalarField(geo, {
                color: chroma.scale(['#9fd0e3', '#faf68e', '#fcdf4c', '#fac043', '#f5a23d', '#f28938', '#f06b32', '#ed4e2b', '#eb3326', '#e6151f']).domain([0,100]),
                opacity: 1.0,
                inFilter: (v) => v !== 0
              });
              probs.push(layerProb);
            } catch(err) {
              expected_probs--;
            }
          });
        }
        // expected_perims = 0;
        // addPerim(0);
        for (i in perim_files)
        {
          addPerim(i);
        }
        // addProb(0);
        for (i in prob_files)
        {
          addProb(i);
        }
        function checkWait()
        {
          if (probs.length != expected_probs || perims.length != expected_perims)
          {
            setTimeout(checkWait, 100);
            return;
          }
          //alert('loaded');
          let perimGroup = L.featureGroup(perims).addTo(map);
          let probGroup = L.featureGroup(probs).addTo(map);
          L.control.layers({
              "Perimeter": perimGroup,
              "Probability": probGroup,
            }, {}, {
            position: 'bottomleft',
            collapsed: false
          }).addTo(map);
          probGroup.on('click', function (e) {
            if (e.value !== null) {
              let v = e.value;
              let html = ('<span class="popupText">Probability ${v}%</span>');
              let popup = L.popup()
                          .setLatLng(e.latlng)
                          .setContent(html)
                          .openOn(map);
              }
            });
          map.fitBounds(probGroup.getBounds());
        }
        setTimeout(checkWait, 100);

    </script>
</body>

</html>

