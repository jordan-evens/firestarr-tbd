from tqdm import tqdm
import multiprocess as mp

POOL = None


def initializer():
    # get an error if don't import in initalizer
    import signal
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def init_pool():
    # ignore Ctrl+C in workers
    return mp.Pool(initializer=initializer,
                   processes=mp.cpu_count())


def pmap(fct, values, *args, **kwargs):
    global POOL
    if POOL is None:
        POOL = init_pool()
    try:
        kwargs['total'] = len(values)
        results = list(tqdm(POOL.imap_unordered(lambda p: (p[0], fct(p[1])),
                                                [(i, v) for i, v in enumerate(values)]),
                            *args,
                            **kwargs))
        return [v[1] for v in sorted(results, key=lambda v: v[0])]
    except KeyboardInterrupt as e:
        POOL.terminate()
        POOL = init_pool()
        raise e
