<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" xmlns:gml="http://www.opengis.net/gml" version="1.0.0" xmlns:ogc="http://www.opengis.net/ogc" xmlns:sld="http://www.opengis.net/sld">
  <UserLayer>
    <sld:LayerFeatureConstraints>
      <sld:FeatureTypeConstraint/>
    </sld:LayerFeatureConstraints>
    <sld:UserStyle>
      <sld:Name>probability_157_2024-06-05</sld:Name>
      <sld:FeatureTypeStyle>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <sld:ChannelSelection>
              <sld:GrayChannel>
                <sld:SourceChannelName>1</sld:SourceChannelName>
              </sld:GrayChannel>
            </sld:ChannelSelection>
            <sld:ColorMap type="intervals">
              <sld:ColorMapEntry opacity="0" label="Not simulated" color="#ffffff" quantity="0"/>
              <sld:ColorMapEntry opacity="0" label="&lt;= 0.0" color="#ffffff" quantity="0"/>
              <sld:ColorMapEntry opacity="0.439216" label="0.0 - 0.1" color="#00b1f2" quantity="0.10000000000000001"/>
              <sld:ColorMapEntry opacity="0.509804" label="0.1 - 0.2" color="#faf68e" quantity="0.20000000000000001"/>
              <sld:ColorMapEntry opacity="0.576471" label="0.2 - 0.3" color="#fcdf4b" quantity="0.29999999999999999"/>
              <sld:ColorMapEntry opacity="0.647059" label="0.3 - 0.4" color="#fac044" quantity="0.40000000000000002"/>
              <sld:ColorMapEntry opacity="0.717647" label="0.4 - 0.5" color="#f5a23d" quantity="0.5"/>
              <sld:ColorMapEntry opacity="0.788235" label="0.5 - 0.6" color="#f28938" quantity="0.59999999999999998"/>
              <sld:ColorMapEntry opacity="0.858824" label="0.6 - 0.7" color="#f06c33" quantity="0.69999999999999996"/>
              <sld:ColorMapEntry opacity="0.929412" label="0.7 - 0.8" color="#ee4f2c" quantity="0.80000000000000004"/>
              <sld:ColorMapEntry label="0.8 - 0.9" color="#eb3326" quantity="0.90000000000000002"/>
              <sld:ColorMapEntry label="> 0.9" color="#e6151f" quantity="1.0000000010000001"/>
              <sld:ColorMapEntry label="Existing" color="#64292a" quantity="2.0000000010000001"/>
              <sld:ColorMapEntry label="Unprocessed" color="#b7b7b7" quantity="999"/>
            </sld:ColorMap>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </UserLayer>
</StyledLayerDescriptor>
