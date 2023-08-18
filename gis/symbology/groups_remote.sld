<?xml version="1.0" encoding="ISO-8859-1"?>
<StyledLayerDescriptor version="1.0.0"
  xsi:schemaLocation="http://www.opengis.net/sld http://schemas.opengis.net/sld/1.0.0/StyledLayerDescriptor.xsd"
  xmlns="http://www.opengis.net/sld" xmlns:ogc="http://www.opengis.net/ogc"
  xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">

  <NamedLayer>
    <Name>FireSTARR Groups</Name>
    <UserStyle>
      <Title>FireSTARR Groups</Title>
      <FeatureTypeStyle>
        <Rule>
          <Title>FireSTARR Groups</Title>
          <PolygonSymbolizer>
            <Fill>
              <GraphicFill>
                <Graphic>
                  <Mark>
                    <WellKnownName>shape://times</WellKnownName>
                    <Fill/>
                    <Stroke>
                      <CssParameter name="stroke">#ADD8E6</CssParameter>
                      <CssParameter name="stroke-width">0.5</CssParameter>
                    </Stroke>
                  </Mark>
                  <Size>
                    <ogc:Literal>20.0</ogc:Literal>
                  </Size>
                </Graphic>
              </GraphicFill>
              <!--
              <CssParameter name="fill">#7CE3F8</CssParameter>
              <CssParameter name="fill-opacity">0.5</CssParameter>
              -->
            </Fill>
            <Stroke>
              <CssParameter name="stroke">#000000</CssParameter>
              <CssParameter name="stroke-width">0.5</CssParameter>
            </Stroke>
          </PolygonSymbolizer>
        </Rule>
      </FeatureTypeStyle>
    </UserStyle>
  </NamedLayer>
</StyledLayerDescriptor>
