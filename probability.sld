<?xml version="1.0" encoding="UTF-8"?>
<StyledLayerDescriptor xmlns="http://www.opengis.net/sld" xmlns:sld="http://www.opengis.net/sld" version="1.0.0" xmlns:gml="http://www.opengis.net/gml" xmlns:ogc="http://www.opengis.net/ogc">
  <UserLayer>
    <sld:LayerFeatureConstraints>
      <sld:FeatureTypeConstraint/>
    </sld:LayerFeatureConstraints>
    <sld:UserStyle>
      <sld:Name>Probability</sld:Name>
      <sld:FeatureTypeStyle>
        <sld:Rule>
          <sld:RasterSymbolizer>
            <sld:Opacity>1</sld:Opacity>
            <sld:ChannelSelection>
              <sld:GrayChannel>
                <sld:SourceChannelName>1</sld:SourceChannelName>
              </sld:GrayChannel>
            </sld:ChannelSelection>
            <sld:ColorMap type="intervals">
              <sld:ColorMapEntry color="#ffffff" opacity="0" quantity="0.0000001" label="&lt;= 0.0"/>
              <sld:ColorMapEntry label="0.000000 - 0.100000" color="#00b2f2" quantity="0.1"/>
              <sld:ColorMapEntry label="0.100000 - 0.200000" color="#25bce3" quantity="0.2"/>
              <sld:ColorMapEntry label="0.200000 - 0.300000" color="#fbf17d" quantity="0.3"/>
              <sld:ColorMapEntry label="0.300000 - 0.400000" color="#fcd449" quantity="0.4"/>
              <sld:ColorMapEntry label="0.400000 - 0.500000" color="#f8b240" quantity="0.5"/>
              <sld:ColorMapEntry label="0.500000 - 0.600000" color="#f4943a" quantity="0.6"/>
              <sld:ColorMapEntry label="0.600000 - 0.700000" color="#f17534" quantity="0.7"/>
              <sld:ColorMapEntry label="0.700000 - 0.800000" color="#ee542c" quantity="0.8"/>
              <sld:ColorMapEntry label="0.800000 - 0.900000" color="#ec3626" quantity="0.9"/>
              <sld:ColorMapEntry label="> 0.900000" color="#e6151f" quantity="inf"/>
            </sld:ColorMap>
          </sld:RasterSymbolizer>
        </sld:Rule>
      </sld:FeatureTypeStyle>
    </sld:UserStyle>
  </UserLayer>
</StyledLayerDescriptor>
