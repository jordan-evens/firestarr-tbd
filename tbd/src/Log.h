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
namespace tbd::logging
{
static const int LOG_EXTENSIVE = 0;
static const int LOG_VERBOSE = 1;
static const int LOG_DEBUG = 2;
static const int LOG_INFO = 3;
static const int LOG_NOTE = 4;
static const int LOG_WARNING = 5;
static const int LOG_ERROR = 6;
static const int LOG_FATAL = 7;
static const int LOG_SILENT = 8;

/**
 * \brief Provides logging functionality.
 */
class Log
{
  /**
   * \brief Current logging level
   */
  static int logging_level_;
public:
  /**
   * \brief Set logging level to a specific level
   * \param log_level Log level to use
   * \return None
   */
  static void setLogLevel(int log_level) noexcept;
  /**
   * \brief Increase amount of logging output by one level
   * \return None
   */
  static void increaseLogLevel() noexcept;
  /**
   * \brief Decrease amount of logging output by one level
   * \return None
   */
  static void decreaseLogLevel() noexcept;
  /**
   * \brief Get current logging level
   * \return Current logging level
   */
  static int getLogLevel() noexcept;
  /**
   * \brief Set output log file
   * \return Return value of open()
   */
  static int openLogFile(const char* filename) noexcept;
  /**
   * \brief Set output log file
   * \return Return value of close()
   */
  static int closeLogFile() noexcept;
};
/**
 * \brief Output a message to the log
 * \param log_level Log level to use for label
 * \param format Format string for message
 * \param args Arguments to use in format string
 * \return None
 */
void output(int log_level, const char* format, va_list* args)
#ifdef NDEBUG
noexcept
#endif
;
/**
 * \brief Output a message to the log
 * \param log_level Log level to use for label
 * \param format Format string for message
 * \param ... Arguments to format message with
 * \return None
 */
void output(int log_level, const char* format, ...)
#ifdef NDEBUG
noexcept
#endif
;
/**
 * \brief Log with EXTENSIVE level
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void extensive(const char* format, ...) noexcept;
/**
 * \brief Log with VERBOSE level
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void verbose(const char* format, ...) noexcept;
/**
 * \brief Log with DEBUG level
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void debug(const char* format, ...) noexcept;
/**
 * \brief Log with INFO level
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void info(const char* format, ...) noexcept;
/**
 * \brief Log with NOTE level
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void note(const char* format, ...) noexcept;
/**
 * \brief Log with WARNING level
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void warning(const char* format, ...) noexcept;
/**
 * \brief Log with ERROR level
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void error(const char* format, ...) noexcept;
/**
 * \brief Check condition and log and exit if true
 * \param condition Condition to check (true ends program after logging)
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void check_fatal(bool condition, const char* format, ...)
#ifdef NDEBUG
noexcept
#endif
;
/**
 * \brief Log with FATAL level and exit
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void fatal(const char* format, ...)
#ifdef NDEBUG
noexcept
#endif
;
/**
 * \brief Log with FATAL level and exit
 * \param ex Exception that is causing fatal error
 */
void fatal(const std::exception& ex);
/**
 * \brief Log with FATAL level and exit
 * \param ex Exception that is causing fatal error
 * \param format Format string for message
 * \param ... Arguments to format message with
 */
void fatal(const std::exception& ex, const char* format, ...);
// templated so we can return it from any function and not get an error
// about not returning on all paths
/**
 * \brief Log a fatal error and quit
 * \tparam T Type to return (so that it can be used to avoid no return value warning)
 * \param format Format string for message
 * \param args Arguments to format message with
 * \return Nothing, because this ends the program
 */
template <class T>
T fatal(const char* format, va_list* args)
#ifdef NDEBUG
noexcept
#endif
{
  output(LOG_FATAL, format, args);
  Log::closeLogFile();
#ifdef NDEBUG
  exit(EXIT_FAILURE);
#else
  // HACK: just throw the format for a start - just want to see stack traces when debugging
  throw std::runtime_error(format);
#endif
}
/**
 * \brief Log a fatal error and quit
 * \tparam T Type to return (so that it can be used to avoid no return value warning)
 * \param format Format string for message
 * \param ... Arguments to format message with
 * \return Nothing, because this ends the program
 */
template <class T>
T fatal(const char* format, ...)
#ifdef NDEBUG
noexcept
#endif
{
  va_list args;
  va_start(args, format);
  // cppcheck-suppress va_end_missing
  return fatal<T>(format, &args);
  //  va_end(args);
}
class SelfLogger
{
protected:
  virtual string add_log(const char* format) const noexcept = 0;
  void log_extensive(const char* format, ...) const noexcept;
  void log_verbose(const char* format, ...) const noexcept;
  void log_debug(const char* format, ...) const noexcept;
  void log_info(const char* format, ...) const noexcept;
  void log_note(const char* format, ...) const noexcept;
  void log_warning(const char* format, ...) const noexcept;
  void log_error(const char* format, ...) const noexcept;
  void log_check_fatal(bool condition, const char* format, ...) const
#ifdef NDEBUG
noexcept
#endif
;
  void log_fatal(const char* format, ...) const
#ifdef NDEBUG
noexcept
#endif
;
};
}
