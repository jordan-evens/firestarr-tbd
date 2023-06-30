import logging
import logging.handlers

DEFAULT_LEVEL = logging.INFO
DEFAULT_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

# don't use basicConfig because we want level to be set so we can change overall
# level later
LOG_DEFAULT = logging.StreamHandler(None)
LOG_FORMATTER_DEFAULT = logging.Formatter(DEFAULT_FORMAT)


def add_handler(handler, level=DEFAULT_LEVEL):
    logger = logging.getLogger()
    handler.setFormatter(LOG_FORMATTER_DEFAULT)
    if level:
        handler.setLevel(level)
    logger.addHandler(handler)
    logger.setLevel(min([h.level for h in logger.handlers]))
    return handler


def add_log_file(file_log, level=None):
    handler = logging.FileHandler(file_log)
    return add_handler(handler, level)


def add_log_rotating(file_log, when="d", interval=1, level=None):
    handler = logging.handlers.TimedRotatingFileHandler(
        file_log, when=when, interval=interval
    )
    return add_handler(handler, level)


add_handler(LOG_DEFAULT)
