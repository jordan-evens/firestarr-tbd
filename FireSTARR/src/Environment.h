// Copyright (c) 2020-2021, Queen's Printer for Ontario.
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Affero General Public License as
// published by the Free Software Foundation, either version 3 of the
// License, or (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Affero General Public License for more details.
//
// You should have received a copy of the GNU Affero General Public License
// along with this program.  If not, see <https://www.gnu.org/licenses/>.

#pragma once
#include <algorithm>
#include <execution>
#include <memory>
#include <string>
#include <utility>
#include <vector>
#include "Cell.h"
#include "ConstantGrid.h"
#include "Event.h"
#include "FuelType.h"
#include "GridMap.h"
#include "IntensityMap.h"
#include "Point.h"
namespace firestarr
{
namespace topo
{
using FuelGrid = data::ConstantGrid<const fuel::FuelType*, FuelSize>;
using SlopeGrid = data::ConstantGrid<SlopeSize>;
using AspectGrid = data::ConstantGrid<AspectSize>;
using ElevationGrid = data::ConstantGrid<ElevationSize>;
/*!
 * \page environment Fire environment
 *
 * The fuel, slope, aspect, and elevation used in simulations is consistent through
 * all simulations. These attributes are loaded from rasters at the start of the
 * process. These rasters must be in a UTM projection, and all rasters for a zone
 * must be named consistently across the different attributes. The GIS scripts
 * provided in the FireGUARD project can generate these rasters for you.
 *
 * Elevation is only read at the ignition point and it is assumed that elevation
 * is the same wherever it is used in a calculation. Despite this, slope and aspect
 * are used for calculations in each cell, and it is only where elevation is
 * specifically used in a formula that this value is referenced.
 *
 * Fuel requires a .lut lookup table file, in the same format that Prometheus
 * expects.
 *
 * Grass curing and leaf-on/off are determined based on time of year, as described
 * elsewhere.
 *
 * Weather and ignition point(s) are the only things that vary between simulations
 * at this point.
 */
/**
 * \brief The area that a Model is run for, with Fuel, Slope, and Aspect grids.
 */
class Environment
{
public:
  /**
   * \brief Load from rasters in folder that have same projection as Perimeter
   * \param lookup FuelLookup to use for translating fuel codes
   * \param path Folder to read rasters from
   * \param point Origin point
   * \param perimeter Perimeter to use projection from
   * \param year Year to look for rasters for if available
   * \return Environment
   */
  [[nodiscard]] static Environment loadEnvironment(const fuel::FuelLookup& lookup,
                                                   const string& path,
                                                   const Point& point,
                                                   const string& perimeter,
                                                   int year);
  /**
   * \brief Load from rasters
   * \param lookup FuelLookup to use for translating fuel codes
   * \param point Origin point
   * \param in_fuel Fuel raster
   * \param in_slope Slope raster
   * \param in_aspect Aspect raster
   * \param in_elevation Elevation raster
   * \return Environment
   */
  [[nodiscard]] static Environment load(const fuel::FuelLookup& lookup,
                                        const Point& point,
                                        const string& in_fuel,
                                        const string& in_slope,
                                        const string& in_aspect,
                                        const string& in_elevation);
  ~Environment();
  /**
   * \brief Determine Coordinates in the grid for the Point
   * \param point Point to find Coordinates for
   * \param flipped Whether the grid data is flipped across the horizontal axis
   * \return Coordinates that would be at Point within this EnvironmentInfo, or nullptr if it is not
   */
  [[nodiscard]] unique_ptr<Coordinates> findCoordinates(
    const Point& point,
    bool flipped) const;
  /**
   * \brief Move constructor
   * \param rhs Environment to move from
   */
  constexpr Environment(Environment&& rhs) noexcept = default;
  /**
   * \brief Copy constructor
   * \param rhs Environment to copy from
   */
  constexpr Environment(const Environment& rhs) noexcept = default;
  /**
   * \brief Move assignment
   * \param rhs Environment to move from
   * \return This, after assignment
   */
  Environment& operator=(Environment&& rhs) noexcept = default;
  /**
   * \brief Copy assignment
   * \param rhs Environment to copy from
   * \return This, after assignment
   */
  Environment& operator=(const Environment& rhs) noexcept = default;
  /**
   * \brief UTM projection that this uses
   * \return UTM projection that this uses
   */
  [[nodiscard]] constexpr const string& proj4() const
  {
    return cells_->proj4();
  }
  /**
   * \brief Number of rows in grid
   * \return Number of rows in grid
   */
  [[nodiscard]] constexpr Idx rows() const
  {
    return cells_->rows();
  }
  /**
   * \brief Number of columns in grid
   * \return Number of columns in grid
   */
  [[nodiscard]] constexpr Idx columns() const
  {
    return cells_->columns();
  }
  /**
   * \brief Cell width and height (m)
   * \return Cell width and height (m)
   */
  [[nodiscard]] constexpr double cellSize() const
  {
    return cells_->cellSize();
  }
  /**
   * \brief Elevation of the origin Point
   * \return Elevation of the origin Point
   */
  [[nodiscard]] constexpr ElevationSize elevation() const
  {
    return elevation_;
  }
  /**
   * \brief Cell at given row and column
   * \param row Row
   * \param column Column
   * \return Cell at given row and column
   */
  [[nodiscard]] constexpr Cell cell(const Idx row, const Idx column) const
  {
    return cells_->at(Location(row, column));
  }
  /**
   * \brief Cell at given Location
   * \param location Location
   * \return Cell at given Location
   */
  [[nodiscard]] constexpr Cell cell(const Location& location) const
  {
    return cells_->at(location);
  }
  /**
   * \brief Cell at Location with given hash
   * \param hash_size Hash
   * \return Cell at Location with given hash
   */
  [[nodiscard]] constexpr Cell cell(const HashSize hash_size) const
  {
    return cells_->at(hash_size);
  }
  /**
   * \brief Cell at Location with offset of row and column from Location of Event
   * \param event Event to use for base Location
   * \param row 
   * \param column 
   * \return 
   */
  [[nodiscard]] constexpr Cell offset(const sim::Event& event,
                                      const Idx row,
                                      const Idx column) const
  {
    const auto& p = event.cell();
    return cell(p.hash() + column + MAX_COLUMNS * row);
  }
  /**
   * \brief Make a ProbabilityMap that covers this Environment
   * \param for_what What type of size this represents
   * \param time Time in simulation this ProbabilityMap represents
   * \param start_time Start time of simulation
   * \param min_value Lower bound of 'low' intensity range
   * \param low_max Upper bound of 'low' intensity range
   * \param med_max Upper bound of 'moderate' intensity range
   * \param max_value Upper bound of 'high' intensity range
   * \return ProbabilityMap with the same extent as this
   */
  [[nodiscard]] sim::ProbabilityMap* makeProbabilityMap(const char* for_what,
                                                        double time,
                                                        double start_time,
                                                        int min_value,
                                                        int low_max,
                                                        int med_max,
                                                        int max_value) const;
  /**
   * \brief Create a GridMap<Other> covering this Environment
   * \tparam Other Type of GridMap
   * \param nodata Value that represents no data
   * \return GridMap<Other> covering this Environment
   */
  template <class Other>
  [[nodiscard]] unique_ptr<data::GridMap<Other>> makeMap(const Other nodata) const
  {
    return make_unique<data::GridMap<Other>>(*cells_, nodata);
  }
  /**
   * \brief Create BurnedData and set burned bits based on Perimeter
   * \return BurnedData with all initially burned locations set
   */
  [[nodiscard]] unique_ptr<sim::BurnedData> makeBurnedData() const
  {
    auto result = make_unique<sim::BurnedData>();
    resetBurnedData(&*result);
    return result;
  }
  /**
   * \brief Reset with known non-fuel cells
   * \param data BurnedData to reset
   */
  void resetBurnedData(sim::BurnedData* data) const noexcept
  {
    *data = not_burnable_;
  }
protected:
  /**
   * \brief Combine rasters into ConstantGrid<Cell>
   * \param fuel Fuel raster
   * \param slope Slope raster
   * \param aspect Aspect raster
   * \return 
   */
  [[nodiscard]] static data::ConstantGrid<Cell>* makeCells(
    const FuelGrid& fuel,
    const SlopeGrid& slope,
    const AspectGrid& aspect,
    const ElevationGrid& elevation)
  {
    logging::check_fatal(fuel.yllcorner() != slope.yllcorner(),
                         "Expected yllcorner %f but got %f",
                         fuel.yllcorner(),
                         slope.yllcorner());
    logging::check_fatal(fuel.yllcorner() != aspect.yllcorner(),
                         "Expected yllcorner %f but got %f",
                         fuel.yllcorner(),
                         aspect.yllcorner());
    static Cell nodata{};
    auto values = vector<Cell>{fuel.data.size()};
    logging::note("Checking slope");
    vector<HashSize> hashes{};
    for (HashSize h = 0; h < static_cast<size_t>(fuel.rows()) * fuel.columns(); ++h)
    {
      hashes.emplace_back(h);
    }
    for (Idx i = 1; i < elevation.rows() - 1; ++i)
    {
      for (Idx j = 1; j < elevation.columns() - 1; ++j)
      {
        double dem[9];
        for (int c = -1; c < 2; ++c)
        {
          for (int r = -1; r < 2; ++r)
          {
            // grid is (0, 0) at bottom left, but want [0] in array to be NW corner
            auto actual_row = static_cast<Idx>(i - r);
            auto actual_column = static_cast<Idx>(j + c);
            auto loc = Location{actual_row, actual_column};
            auto h = loc.hash();
            dem[3 * (r + 1) + (c + 1)] = 1.0 * elevation.at(h);
          }
        }
        // Horn's algorithm
        const double dx = ((dem[2] + dem[5] + dem[5] + dem[8])
                           - (dem[0] + dem[3] + dem[3] + dem[6]))
                        / elevation.cellSize();
        const double dy = ((dem[6] + dem[7] + dem[7] + dem[8])
                           - (dem[0] + dem[1] + dem[1] + dem[2]))
                        / elevation.cellSize();
        const double key = (dx * dx + dy * dy);
        auto slope_pct = static_cast<float>(100 * (sqrt(key) / 8.0));
        auto s = slope_pct;
        auto s_int = static_cast<SlopeSize>(round(s));
        auto loc = Location{i, j};
        auto h = loc.hash();
        const auto s_orig = min(static_cast<SlopeSize>(MAX_SLOPE_FOR_DISTANCE),
                                slope.at(h));
        const auto a_orig = 0 == s_int ? static_cast<AspectSize>(0) : aspect.at(h);
        const auto f = fuel::FuelType::safeCode(fuel.at(h));
        const auto cell = Cell(h, s_orig, a_orig, f);
        const auto s_real = cell.slope();
        const auto s_grid = slope.at(h);
        const auto a_real = cell.aspect();

        float a = 0.0;

        if (dx != 0 || dy != 0)
        {
          a = static_cast<float>(atan2(dy, -dx) * M_RADIANS_TO_DEGREES);
          a = (a > 90.0f) ? (450.0f - a) : (90.0f - a);
          if (a == 360.0f)
          {
            a = 0.0;
          }
        }

        auto a_grid = aspect.at(h);
        auto a_int = static_cast<AspectSize>(round(a));
        if (s_int != s_grid || a_int != a_grid)
        {
          printf("%f | %f | %f\n", dem[0], dem[1], dem[2]);
          printf("%f | %f | %f\n", dem[3], dem[4], dem[5]);
          printf("%f | %f | %f\n", dem[6], dem[7], dem[8]);
          printf("%f     %f\n", dx, dy);
          logging::debug("Slope %d from %f => %d/%d", s_int, s, s_real, s_grid);
          logging::debug("Aspect %d from %f => %d/%d", a_int, a, a_real, a_grid);
          logging::fatal("Slope and aspect calculation produced incorrect results");
        }
      }
    }
    logging::note("Done checking slope");
    std::for_each(
      std::execution::par_unseq,
      hashes.begin(),
      hashes.end(),
      [&fuel, &slope, &aspect, &values](auto&& h)
      {
        const auto s = min(static_cast<SlopeSize>(MAX_SLOPE_FOR_DISTANCE),
                           slope.at(h));
        const auto a = 0 == s ? static_cast<AspectSize>(0) : aspect.at(h);
        const auto f = fuel::FuelType::safeCode(fuel.at(h));
        const auto cell = Cell(h, s, a, f);
        values.at(h) = cell;
#ifndef NDEBUG
#ifndef VLD_RPTHOOK_INSTALL
        const topo::Location loc{h};
        const auto r = loc.row();
        const auto c = loc.column();
        logging::check_fatal(cell.row() != r, "Cell row %d not %d", cell.row(), r);
        logging::check_fatal(cell.column() != c, "Cell column %d not %d", cell.column(), c);
        logging::check_fatal(cell.slope() != s, "Cell slope %d not %d", cell.slope(), s);
        logging::check_fatal(cell.aspect() != a, "Cell aspect %d not %d", cell.aspect(), a);
        logging::check_fatal(cell.fuelCode() != f, "Cell fuel %d not %d", cell.fuelCode(), f);
        const auto v = values.at(h);
        logging::check_fatal(v.row() != r, "Row %d not %d", v.row(), r);
        logging::check_fatal(v.column() != c, "Column %d not %d", v.column(), c);
        logging::check_fatal(v.slope() != s, "Slope %d not %d", v.slope(), s);
        if (0 != s)
        {
          logging::check_fatal(v.aspect() != a, "Aspect %d not %d", v.aspect(), a);
        }
        else
        {
          logging::check_fatal(v.aspect() != 0, "Aspect %d not %d", v.aspect(), 0);
        }
        logging::check_fatal(v.fuelCode() != f, "Fuel %d not %d", v.fuelCode(), f);
#endif
#endif
      });
    return new data::ConstantGrid<Cell>(fuel.cellSize(),
                                        fuel.rows(),
                                        fuel.columns(),
                                        nodata,
                                        -1,
                                        fuel.xllcorner(),
                                        fuel.yllcorner(),
                                        fuel.xurcorner(),
                                        fuel.yurcorner(),
                                        string(fuel.proj4()),
                                        std::move(values));
  }
  /**
   * \brief Creates a map of areas that are not burnable either because of fuel or the initial perimeter.
   */
  void initializeNotBurnable()
  {
    // make a template we can copy to reset things
    for (Idx r = 0; r < rows(); ++r)
    {
      for (Idx c = 0; c < columns(); ++c)
      {
        const Location location(r, c);
        if (fuel::is_null_fuel(cell(location)))
        {
          not_burnable_[location.hash()] = true;
        }
      }
    }
  }
  /**
   * \brief Load from rasters
   * \param fuel Fuel raster
   * \param slope Slope raster
   * \param aspect Aspect raster
   * \param elevation Elevation raster
   */
  Environment(
    const FuelGrid& fuel,
    const SlopeGrid& slope,
    const AspectGrid& aspect,
    const ElevationGrid& elevation)
    : cells_(makeCells(fuel,
                       slope,
                       aspect,
                       elevation))
  {
    // HACK: just take elevation in middle of grid since that's where fire should be
    elevation_ = elevation.at(Location{MAX_ROWS / 2, MAX_COLUMNS / 2});
    logging::note("Start elevation is %d", elevation_);
    initializeNotBurnable();
  }
  /**
   * \brief Construct from cells and elevation
   * \param cells Cells representing Environment
   * \param elevation Elevation at origin Point
   */
  Environment(data::ConstantGrid<Cell>* cells,
              const ElevationSize elevation) noexcept
    : cells_(cells), elevation_(elevation)
  {
    try
    {
      initializeNotBurnable();
    }
    catch (...)
    {
      std::terminate();
    }
  }
private:
  /**
   * \brief Cells representing Environment
   */
  data::ConstantGrid<Cell>* cells_;
  /**
   * \brief BurnedData of cells that are not burnable
   */
  sim::BurnedData not_burnable_{};
  /**
   * \brief Elevation at StartPoint
   */
  ElevationSize elevation_;
};
}
}
