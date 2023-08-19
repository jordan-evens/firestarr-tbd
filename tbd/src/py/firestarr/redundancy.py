import traceback

from fiona.errors import FionaError

NUM_RETRIES = 5


def get_stack(ex):
    return "".join(traceback.format_exception(ex))


def call_safe(fct, *args, **kwargs):
    retries = NUM_RETRIES
    while True:
        try:
            return fct(*args, **kwargs)
        except Exception as ex:
            str_stack = get_stack(ex)
            ignore_ok = isinstance(ex, OSError) and 5 == ex.errno
            ignore_ok = ignore_ok or (
                (isinstance(ex, FionaError) or isinstance(ex, RuntimeError))
                and "Input/output error" in str_stack
            )
            # ignore because azure is throwing them all the time
            # OSError: [Errno 5] Input/output
            if retries <= 0 or not ignore_ok:
                print(str_stack)
                raise ex
            retries -= 1
        except Exception as ex:
            raise ex
