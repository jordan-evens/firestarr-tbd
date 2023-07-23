import itertools

import multiprocess as mp
import numpy as np
from tqdm import tqdm

MAX_PROCESSES = mp.cpu_count()
# # HACK: trying to keep things from freezing all the time lately
# DEFAULT_PROCESSES = max(1, int(mp.cpu_count() / 4))


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
    return mp.Pool(initializer=initializer, processes=processes)


def pmap(fct, values, max_processes=None, no_limit=False, *args, **kwargs):
    if 1 == max_processes or (not no_limit and 1 == MAX_PROCESSES):
        # don't bother with pool if only one process
        return [fct(x) for x in tqdm(values, *args, **kwargs)]
    pool = init_pool(max_processes, no_limit)
    try:
        kwargs["total"] = len(values)
        results = list(
            tqdm(
                pool.imap_unordered(
                    lambda p: (p[0], fct(p[1])), [(i, v) for i, v in enumerate(values)]
                ),
                *args,
                **kwargs,
            )
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
    fct = fct
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
            pbar := tqdm(
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
