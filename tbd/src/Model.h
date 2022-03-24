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
#include <condition_variable>
#include <cstdio>
#include <future>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <vector>
#include "Environment.h"
#include "Iteration.h"
namespace tbd
{
namespace topo
{
class StartPoint;
}
namespace sim
{
class Event;
class Scenario;
/**
 * \brief Provides the ability to limit number of threads running at once.
 */
class Semaphore
{
public:
  /**
   * \brief Create a Semaphore that limits number of concurrent things running
   * \param n Number of concurrent things running
   */
  explicit Semaphore(const int n)
    : count_{n}
  {
    logging::note("Semaphore count is %d", count_);
  }
  Semaphore(const Semaphore& rhs) = delete;
  Semaphore(Semaphore&& rhs) = delete;
  Semaphore& operator=(const Semaphore& rhs) = delete;
  Semaphore& operator=(Semaphore&& rhs) = delete;
  /**
   * \brief Notify something that's waiting so it can run
   */
  void notify()
  {
    std::unique_lock<std::mutex> l(mutex_);
    ++count_;
    cv_.notify_one();
  }
  /**
   * \brief Wait until allowed to run
   */
  void wait()
  {
    std::unique_lock<std::mutex> l(mutex_);
    cv_.wait(l, [this]
             {
               return count_ != 0;
             });
    --count_;
  }
private:
  /**
   * \brief Mutex for parallel access
   */
  std::mutex mutex_;
  /**
   * \brief Condition variable to use for checking count
   */
  std::condition_variable cv_;
  /**
   * \brief Variable to keep count of threads in use
   */
  int count_;
};
/**
 * \brief Indicates a section of code that is limited to a certain number of threads running at once.
 */
class CriticalSection
{
  /**
   * \brief Semaphore that this keeps track of access for
   */
  Semaphore& s_;
public:
  /**
   * \brief Constructor
   * \param ss Semaphore to wait on
   */
  explicit CriticalSection(Semaphore& ss)
    : s_{ss}
  {
    s_.wait();
  }
  CriticalSection(const CriticalSection& rhs) = delete;
  CriticalSection(CriticalSection&& rhs) = delete;
  CriticalSection& operator=(const CriticalSection& rhs) = delete;
  CriticalSection& operator=(CriticalSection&& rhs) = delete;
  ~CriticalSection() noexcept
  {
    try
    {
      s_.notify();
    }
    catch (...)
    {
      std::terminate();
    }
  }
};
/**
 * \brief Contains all the immutable information regarding a simulation that is common between Scenarios.
 */
class Model
{
public:
  /**
   * \brief Run Scenarios initialized from given inputs
   * \param weather_input Name of file to read weather from
   * \param raster_root Directory to read raster inputs from
   * \param yesterday FwiWeather yesterday used for startup indices
   * \param start_point StartPoint to use for sunrise/sunset
   * \param start_time Start time for simulation
   * \param save_intensity Whether or not to save all intensity files
   * \param perimeter Perimeter to initialize fire from, if there is one
   * \param size Size to start fire at if no Perimeter
   * \return 
   */
  [[nodiscard]] static int runScenarios(const char* weather_input,
                                        const char* raster_root,
                                        const wx::FwiWeather& yesterday,
                                        const topo::StartPoint& start_point,
                                        const tm& start_time,
                                        bool save_intensity,
                                        const string& perimeter,
                                        size_t size);
  /**
   * \brief Cell at the given row and column
   * \param row Row
   * \param column Column
   * \return Cell at the given row and column
   */
  [[nodiscard]] constexpr topo::Cell cell(const Idx row, const Idx column) const
  {
    return env_->cell(row, column);
  }
  /**
   * \brief Cell at the given Location
   * \param location Location to get Cell for
   * \return Cell at the given Location
   */
  [[nodiscard]] constexpr topo::Cell cell(const Location& location) const
  {
    return env_->cell(location);
  }
  /**
   * \brief Cell at the Location represented by the given hash
   * \param hash_size Hash size for Location to get Cell for
   * \return Cell at the Location represented by the given hash
   */
  //  [[nodiscard]] constexpr topo::Cell cell(const HashSize hash_size) const
  //  {
  //    return env_->cell(hash_size);
  //  }
  /**
   * \brief Number of rows in extent
   * \return Number of rows in extent
   */
  [[nodiscard]] constexpr Idx rows() const
  {
    return env_->rows();
  }
  /**
   * \brief Number of columns in extent
   * \return Number of columns in extent
   */
  [[nodiscard]] constexpr Idx columns() const
  {
    return env_->columns();
  }
  /**
   * \brief Cell width and height (m)
   * \return Cell width and height (m)
   */
  [[nodiscard]] constexpr double cellSize() const
  {
    return env_->cellSize();
  }
  /**
   * \brief Environment simulation is occurring in
   * \return Environment simulation is occurring in
   */
  [[nodiscard]] constexpr const topo::Environment& environment() const
  {
    return *env_;
  }
  /**
   * \brief Time to use for simulation start 
   * \return Time to use for simulation start
   */
  [[nodiscard]] constexpr Clock::time_point startTime() const
  {
    return start_time_;
  }
  /**
   * \brief Maximum amount of time simulation can run for before being stopped
   * \return Maximum amount of time simulation can run for before being stopped
   */
  [[nodiscard]] constexpr Clock::duration timeLimit() const
  {
    return time_limit_;
  }
  /**
   * \brief Whether or not simulation has been running longer than maximum duration
   * \return Whether or not simulation has been running longer than maximum duration
   */
  [[nodiscard]] bool isOutOfTime() const noexcept;
  /**
   * \brief Difference between date and the date of minimum foliar moisture content
   * \param time Date to get value for
   * \return Difference between date and the date of minimum foliar moisture content
   */
  [[nodiscard]] constexpr int nd(const double time) const
  {
    return nd_.at(static_cast<Day>(time));
  }
  /**
   * \brief Create a ProbabilityMap with the same extent as this
   * \param time Time in simulation this ProbabilityMap represents
   * \param start_time Start time of simulation
   * \param min_value Lower bound of 'low' intensity range
   * \param low_max Upper bound of 'low' intensity range
   * \param med_max Upper bound of 'moderate' intensity range
   * \param max_value Upper bound of 'high' intensity range
   * \return ProbabilityMap with the same extent as this
   */
  [[nodiscard]] ProbabilityMap* makeProbabilityMap(double time,
                                                   double start_time,
                                                   int min_value,
                                                   int low_max,
                                                   int med_max,
                                                   int max_value) const;
  ~Model() = default;
  /**
   * \brief Constructor
   * \param start_point StartPoint to use for sunrise/sunset times
   * \param env Environment to run simulations in
   */
  Model(const topo::StartPoint& start_point,
        topo::Environment* env);
  Model(Model&& rhs) noexcept = delete;
  Model(const Model& rhs) = delete;
  Model& operator=(Model&& rhs) noexcept = delete;
  Model& operator=(const Model& rhs) = delete;
  /**
   * \brief Read weather used for Scenarios
   * \param filename Weather file to read
   * \param yesterday FwiWeather for yesterday
   * \param latitude to use for calculating DC & DMC
   */
  void readWeather(const string& filename,
                   const wx::FwiWeather& yesterday,
                   double latitude);
  /**
   * \brief Make starts based on desired point and where nearest combustible cells are
   * \param coordinates Coordinates in the Environment to try starting at
   * \param point Point Coordinates represent
   * \param yesterday FwiWeather for yesterday
   * \param perim Perimeter to start from, if there is one
   * \param size Size of fire to create if no input Perimeter
   */
  void makeStarts(Coordinates coordinates,
                  const topo::Point& point,
                  const wx::FwiWeather& yesterday,
                  const string& perim,
                  size_t size);
  /**
   * \brief Create an Iteration by initializing Scenarios
   * \param start_point StartPoint to use for sunrise/sunset
   * \param start Start time for simulation
   * \param save_intensity Whether or not to save all intensity files too
   * \param start_day Start date for simulation
   * \param last_date End date for simulation
   * \return Iteration containing initialized Scenarios
   */
  [[nodiscard]] Iteration readScenarios(const topo::StartPoint& start_point,
                                        double start,
                                        bool save_intensity,
                                        Day start_day,
                                        Day last_date);
  /**
   * \brief Acquire a BurnedData that has already burnt cells set
   * \return A BurnedData that has already burnt cells set
   */
  [[nodiscard]] BurnedData* getBurnedVector() const noexcept;
  /**
   * \brief Return a BurnedData so it can be used in the future
   * \param has_burned BurnedData to return to pool
   */
  void releaseBurnedVector(BurnedData* has_burned) const noexcept;
  /**
   * \brief Semaphore used to limit how many things run at once
   */
  static Semaphore task_limiter;
private:
  /**
   * \brief Mutex for parallel access
   */
  mutable mutex vector_mutex_;
  /**
   * \brief Pool of BurnedData that can be reused
   */
  mutable vector<unique_ptr<BurnedData>> vectors_{};
  /**
   * \brief Run Iterations until confidence is reached
   * \param start_point StartPoint to use for sunrise/sunset
   * \param start Start time for simulation
   * \param start_day Start day for simulation
   * \param save_intensity Whether or not to save all intensity files
   * \return Map of times to ProbabilityMap for that time
   */
  map<double, ProbabilityMap*> runIterations(const topo::StartPoint& start_point,
                                             double start,
                                             Day start_day,
                                             bool save_intensity);
  /**
   * \brief Find Cell(s) that can burn closest to Location
   * \param location Location to look for start Cells
   */
  void findStarts(Location location);
  /**
   * \brief Differences between date and the date of minimum foliar moisture content
   */
  array<int, MAX_DAYS> nd_{};
  /**
   * \brief Map of scenario number to weather stream
   */
  map<size_t, shared_ptr<wx::FireWeather>> wx_{};
  /**
   * \brief Cell(s) that can burn closest to start Location
   */
  vector<shared_ptr<topo::Cell>> starts_{};
  /**
   * \brief Time to use for simulation start 
   */
  Clock::time_point start_time_;
  /**
   * \brief Maximum amount of time simulation can run for before being stopped
   */
  Clock::duration time_limit_;
  /**
   * \brief Perimeter to use for initializing simulations
   */
  shared_ptr<topo::Perimeter> perimeter_ = nullptr;
  /**
   * \brief Environment to use for Model
   */
  topo::Environment* env_;
};
}
}
