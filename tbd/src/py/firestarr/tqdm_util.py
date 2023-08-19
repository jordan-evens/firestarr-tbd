import collections
import contextlib
import itertools

import multiprocess
import multiprocess.pool
import multiprocess.queues
import numpy as np
import pandas as pd
from multiprocess.reduction import ForkingPickler
from redundancy import call_safe
from tqdm.auto import tqdm

MAX_PROCESSES = multiprocess.cpu_count()
TQDM_DEPTH = multiprocess.Value("i", 0)
DEFAULT_KEEP_ALL = True
KEEP_LEVELS = 2
TqdmArgs = collections.namedtuple("TqdmArgs", ["position", "leave"])


def get_safe(self):
    with self._rlock:
        res = self._reader.recv_bytes()
    # unserialize the data after having released the lock
    return call_safe(ForkingPickler.loads, res)


def put_safe(self, obj):
    # serialize the data before acquiring the lock
    obj = call_safe(ForkingPickler.dumps, obj)
    if self._wlock is None:
        # writes to a message oriented win32 pipe are atomic
        self._writer.send_bytes(obj)
    else:
        with self._wlock:
            self._writer.send_bytes(obj)


# HACK: try overriding methods for Pool pickling to prevent azure i/o errors
multiprocess.queues.SimpleQueue.get = get_safe
multiprocess.queues.SimpleQueue.put = put_safe


@contextlib.contextmanager
def tqdm_depth(keep_all=DEFAULT_KEEP_ALL):
    global TQDM_DEPTH
    position = TQDM_DEPTH.value
    obj = TqdmArgs(position, keep_all or KEEP_LEVELS > position)
    try:
        TQDM_DEPTH.value += 1
        yield obj
    finally:
        TQDM_DEPTH.value -= 1


def apply(onto, fct=None, *args, **kwargs):
    with tqdm_depth() as tq:
        kwargs["position"] = tq.position
        kwargs["leave"] = tq.leave
        if isinstance(onto, pd.DataFrame) or isinstance(onto, pd.Series):
            if fct is None:
                raise RuntimeError("Must specify function if using Series or DataFrame")
            #  prep so progress_apply() works
            tqdm.pandas(*args, **kwargs)
            # apply to axis if not Series
            return (
                onto.progress_apply(fct)
                if isinstance(onto, pd.Series)
                else onto.progress_apply(fct, axis=1)
            )
        return (
            [fct(x) for x in tqdm(onto, *args, **kwargs)]
            if fct is not None
            else tqdm(onto, *args, **kwargs)
        )


def wrap_write(chunks, save_as, mode, *args, **kwargs):
    with tqdm_depth() as tq:
        kwargs["position"] = tq.position
        kwargs["leave"] = tq.leave
        kwargs["miniters"] = 1
        with tqdm.wrapattr(open(save_as, mode), "write", *args, **kwargs) as fout:
            for chunk in chunks:
                fout.write(chunk)
        return save_as


def initializer():
    # get an error if don't import in initalizer
    import signal

    signal.signal(signal.SIGINT, signal.SIG_IGN)


def init_pool(processes=None, no_limit=False):
    if processes is None:
        processes = MAX_PROCESSES
    # allow overriding above number of cpus if really wanted
    if not no_limit:
        # no point in starting more than the number of cpus?
        processes = min(processes, MAX_PROCESSES)
    # ignore Ctrl+C in workers
    return multiprocess.pool.Pool(
        initializer=initializer,
        # context=SafeForkContext(),
        processes=processes,
    )


def pmap(fct, values, max_processes=None, no_limit=False, *args, **kwargs):
    if 1 == max_processes or (not no_limit and 1 == MAX_PROCESSES):
        # don't bother with pool if only one process
        return [fct(x) for x in apply(values, *args, **kwargs)]
    pool = init_pool(max_processes, no_limit)
    try:
        kwargs["total"] = len(values)
        results = apply(
            pool.imap_unordered(
                lambda p: (p[0], fct(p[1])),
                [(i, v) for i, v in enumerate(values)],
            ),
            *args,
            **kwargs,
        )
        result = [v[1] for v in sorted(results, key=lambda v: v[0])]
        return result
    finally:
        # avoid Exception ignored in: <function Pool.__del__ at 0x7f8fd4c75d30>
        pool.terminate()


def pmap_by_group(
    fct,
    values,
    callback_group=None,
    max_processes=None,
    no_limit=False,
    *args,
    **kwargs,
):
    if not hasattr(values, "values"):
        return pmap(
            fct, values, max_processes=max_processes, no_limit=no_limit, *args, **kwargs
        )

    pool = init_pool(max_processes, no_limit)
    _desc = f"{kwargs['desc']}: " if "desc" in kwargs else ""
    # HACK: let dictionary show progress by groups
    values = values
    all_values = list(itertools.chain.from_iterable(values.values()))
    lengths = {k: len(v) for k, v in values.items()}
    groups = list(lengths.keys())
    num = list(lengths.values())
    breaks = list(np.cumsum(list(lengths.values())))
    ranges = {groups[i]: list(zip([0] + breaks, breaks))[i] for i in range(len(breaks))}
    groups_by_index = list(
        itertools.chain.from_iterable(
            [[groups[i]] * num[i] for i in range(len(groups))]
        )
    )
    groups_left = {groups[i]: num[i] for i in range(len(groups))}
    groups_done = list()
    groups_pending = list(groups)
    completed = []

    try:
        kwargs["total"] = len(all_values)
        result = {}
        results = [None] * len(all_values)
        for i, v in (
            pbar := apply(
                pool.imap_unordered(
                    lambda p: (p[0], fct(p[1])),
                    [(i, v) for i, v in enumerate(all_values)],
                ),
                *args,
                **kwargs,
            )
        ):
            results[i] = v
            g = groups_by_index[i]
            groups_left[g] -= 1
            if 0 == groups_left[g]:
                groups_done.append(g)
                groups_pending.remove(g)
                completed.extend(values[g])
                j, k = ranges[g]
                result[g] = results[j:k]
                if callback_group:
                    callback_group(g, result[g])
            pbar.set_description(
                f"{_desc}{groups_done}/{groups_pending}".replace("]/[", "::")
            )
        return result
    finally:
        # avoid Exception ignored in: <function Pool.__del__ at 0x7f8fd4c75d30>
        pool.terminate()
