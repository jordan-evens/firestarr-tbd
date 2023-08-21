import collections
import contextlib
import itertools

import multiprocess
import multiprocess.pool
import multiprocess.queues
import numpy as np
import pandas as pd
from tqdm.auto import tqdm

MAX_PROCESSES = multiprocess.cpu_count()
TQDM_DEPTH = multiprocess.Value("i", 0)
DEFAULT_KEEP_ALL = True
KEEP_LEVELS = 2
MINITERS = 2
TqdmArgs = collections.namedtuple("TqdmArgs", ["position", "leave"])


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


def apply_direct(fct, values, try_only=False, *args, **kwargs):
    total = kwargs.get("total", None) or (
        len(values) if hasattr(values, "__len__") else None
    )
    if 0 == total:
        # nothing to do
        return []
    if 1 == total:
        # don't loop if just one thing
        return [fct(values[0])]
    if try_only:
        return None
    return (
        [fct(x) for x in tqdm(values, *args, **kwargs)]
        if fct is not None
        else tqdm(values, *args, **kwargs)
    )


def apply(onto, fct=None, *args, **kwargs):
    with tqdm_depth() as tq:
        kwargs["position"] = tq.position
        kwargs["leave"] = tq.leave
        kwargs["miniters"] = MINITERS
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
        return apply_direct(fct, onto, *args, **kwargs)


def wrap_write(chunks, save_as, mode, *args, **kwargs):
    with tqdm_depth() as tq:
        kwargs["position"] = tq.position
        kwargs["leave"] = tq.leave
        kwargs["miniters"] = MINITERS
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
    # check if there's no point in looping
    result_direct = apply_direct(fct, values, try_only=True, *args, **kwargs)
    if result_direct is not None:
        return result_direct
    is_single = (1 == max_processes) or (not no_limit and 1 == MAX_PROCESSES)
    if is_single:
        # don't bother with pool if only one process
        return [fct(x) for x in apply(values, *args, **kwargs)]
    pool = init_pool(max_processes, no_limit)
    try:
        kwargs["total"] = kwargs.get("total", len(values))
        kwargs["miniters"] = MINITERS
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
        kwargs["miniters"] = MINITERS
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
