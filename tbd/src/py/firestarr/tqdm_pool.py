import multiprocess as mp
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
                **kwargs
            )
        )
        result = [v[1] for v in sorted(results, key=lambda v: v[0])]
        # avoid Exception ignored in: <function Pool.__del__ at 0x7f8fd4c75d30>
        pool.terminate()
        return result
    except KeyboardInterrupt as e:
        pool.terminate()
        raise e
