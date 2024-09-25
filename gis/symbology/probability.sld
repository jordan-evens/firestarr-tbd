<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc" version="1.0.0" xmlns:gml="http://www.opengis.net/gml" xmlns:sld="http://www.opengis.net/sld">
  <UserLayer>
    <sld:LayerFeatureConstraints>
      <sld:FeatureTypeConstraint/>
    </sld:LayerFeatureConstraints>
    <sld:UserStyle>
      <sld:Name>Probability</sld:Name>
      <sld:FeatureTypeStyle>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <sld:ChannelSelection>
              <sld:GrayChannel>
                <sld:SourceChannelName>1</sld:SourceChannelName>
              </sld:GrayChannel>
            </sld:ChannelSelection>
            <sld:ColorMap type="intervals">
              <sld:ColorMapEntry color="#ffffff" opacity="0" quantity="0" label="Not simulated"/>
              <sld:ColorMapEntry color="#ffffff" opacity="0" quantity="0.000000001" label="&lt;= 0.0"/>
              <sld:ColorMapEntry color="#00b1f2" quantity="0.1" label="0.0 - 0.1"/>
              <sld:ColorMapEntry color="#faf68e" quantity="0.2" label="0.1 - 0.2"/>
              <sld:ColorMapEntry color="#fcdf4b" quantity="0.3" label="0.2 - 0.3"/>
              <sld:ColorMapEntry color="#fac044" quantity="0.4" label="0.3 - 0.4"/>
              <sld:ColorMapEntry color="#f5a23d" quantity="0.5" label="0.4 - 0.5"/>
              <sld:ColorMapEntry color="#f28938" quantity="0.6" label="0.5 - 0.6"/>
              <sld:ColorMapEntry color="#f06c33" quantity="0.7" label="0.6 - 0.7"/>
              <sld:ColorMapEntry color="#ee4f2c" quantity="0.8" label="0.7 - 0.8"/>
              <sld:ColorMapEntry color="#eb3326" quantity="0.9" label="0.8 - 0.9"/>
              <sld:ColorMapEntry color="#e6151f" quantity="1.000000001" label="> 0.9"/>
              <sld:ColorMapEntry color="#64292a" quantity="2.000000001" label="Existing"/>
              <sld:ColorMapEntry color="#b7b7b7" quantity="999" label="Unprocessed"/>
            </sld:ColorMap>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </UserLayer>
</StyledLayerDescriptor>
