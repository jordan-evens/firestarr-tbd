import traceback
from io import BytesIO
from pickle import UnpicklingError

import dill._dill
from fiona.errors import FionaError

# from multiprocess.reduction import ForkingPickler

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
                and (
                    "Input/output error" in str_stack
                    or "I/O error" in str_stack
                    or "Resource temporarily unavailable" in str_stack
                )
            )
            # ignore because azure is throwing them all the time
            # OSError: [Errno 5] Input/output
            if retries <= 0 or not ignore_ok:
                print(str_stack)
                raise ex
            retries -= 1


# def load_safe(*args, **kwargs):
#     return call_safe(dill._dill.Unpickler.load, *args, **kwargs)

if not hasattr(dill._dill.Unpickler, "old_init"):
    dill._dill.Unpickler.old_init = dill._dill.Unpickler.__init__


def safe_init(self, *args, **kwds):
    # # HACK: this is horrible because it copies everything that happens
    # #       but read the bytes into memory so we can reset it if needed
    # for i in range(len(args)):
    #     arg = args[i]
    #     if isinstance(arg, BytesIO):
    #         args[i] = BytesIO(arg)
    dill._dill.Unpickler.old_init(self, *args, **kwds)
    # remove unused argument as per old __init__
    kwds.pop("ignore", None)
    # make a copy of ByteIO objects
    self._init_args = args
    self._init_kwds = kwds
    # for i in range(len(self._init_args)):
    #     arg = self._init_args[i]
    #     if isinstance(arg, BytesIO):
    #         # reset to start of BytesIO
    #         print(f"seek 0 for arg {i}")
    #         arg.seek(0)


# HACK: tweak code to handle OSError
def load_safe(self):  # NOTE: if settings change, need to update attributes
    retries = NUM_RETRIES
    obj = None
    while True:
        try:
            obj = dill._dill.StockUnpickler.load(self)
            break
        except OSError as ex:
            print(str(ex))
            if retries <= 0 or 5 != ex.errno:
                raise ex
        except UnpicklingError as ex:
            print(str(ex))
            if retries <= 0 or "[Errno 5] Input/output error" not in str(ex):
                raise ex
        except Exception as ex:
            print(str(ex))
            raise ex
        print("Retrying")
        # need to reinitialize
        args = self._init_args + self._init_kwds.values()
        for arg in args:
            if isinstance(arg, BytesIO):
                # reset to start of BytesIO
                arg.seek(0)
        # for i in range(len(self._init_args)):
        #     arg = self._init_args[i]
        #     if isinstance(arg, BytesIO):
        #         # reset to start of BytesIO
        #         print(f"seek 0 for arg {i}")
        #         arg.seek(0)
        dill._dill.StockUnpickler.__init__(self, *self._init_args, **self._init_kwds)
        print(f"Reinitialized with:\n\t{self._init_args}\n\t{self._init_kwds}")
        retries -= 1
    if type(obj).__module__ == getattr(self._main, "__name__", "__main__"):
        if not self._ignore:
            # point obj class to main
            try:
                obj.__class__ = getattr(self._main, type(obj).__name__)
            except (AttributeError, TypeError):
                pass  # defined in a file
    # _main_module.__dict__.update(obj.__dict__) #XXX: should update globals ?
    return obj


# def save_safe(*args, **kwargs):
#     return call_safe(dill._dill.Pickler.save, *args, **kwargs)

dill._dill.Unpickler.__init__ = safe_init
dill._dill.Unpickler.load = load_safe
# dill._dill.Pickler.save = save_safe
