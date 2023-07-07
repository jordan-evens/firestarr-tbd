from logging import DEBUG, INFO, WARNING, ERROR, FATAL
from logging import getLogger, StreamHandler, Formatter, FileHandler

import logging.handlers as handlers

DEFAULT_LEVEL = INFO
DEFAULT_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"


# HACK: want to have a thing called "logging" that refers to our own logger
#       so that we don't need to change usage everywhere
LOGGER_NAME = "firestarr"
logging = getLogger(LOGGER_NAME)
logging.DEBUG = DEBUG
logging.INFO = INFO
logging.WARNING = WARNING
logging.ERROR = ERROR
logging.FATAL = FATAL

# don't use basicConfig because we want level to be set so we can change overall
# level later
LOG_DEFAULT = StreamHandler(None)
LOG_FORMATTER_DEFAULT = Formatter(DEFAULT_FORMAT)


def add_handler(handler, level=DEFAULT_LEVEL):
    logger = getLogger()
    handler.setFormatter(LOG_FORMATTER_DEFAULT)
    if level:
        handler.setLevel(level)
    logger.addHandler(handler)
    logger.setLevel(min([h.level for h in logger.handlers]))
    return handler


def add_log_file(file_log, level=None):
    handler = FileHandler(file_log)
    return add_handler(handler, level)


def add_log_rotating(file_log, when="d", interval=1, level=None):
    handler = handlers.TimedRotatingFileHandler(
        file_log, when=when, interval=interval
    )
    return add_handler(handler, level)


add_handler(LOG_DEFAULT)
