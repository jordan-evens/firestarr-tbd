import os
import sys
import time

import pandas as pd
from common import (
    DEFAULT_FILE_LOG_LEVEL,
    DIR_LOG,
    DIR_OUTPUT,
    FILE_CURRENT,
    FILE_LATEST,
    SECONDS_PER_MINUTE,
    WX_MODEL,
    locks_for,
    logging,
)
from datasources.spotwx import get_model_dir_uncached, set_model_dir
from log import add_log_rotating
from run import Run, make_resume

LOG_MAIN = add_log_rotating(
    os.path.join(DIR_LOG, "firestarr.log"), level=DEFAULT_FILE_LOG_LEVEL
)
logging.info("Starting main.py")
WAIT_WX = SECONDS_PER_MINUTE * 5

sys.path.append(os.path.dirname(sys.executable))
sys.path.append("/usr/local/bin")

if __name__ == "__main__":
    logging.info("Called with args %s", str(sys.argv))
    args = sys.argv[1:]

    def check_arg(a, args):
        flag = False
        if a in args:
            args.remove(a)
            flag = True
        logging.info(f"Flag for {a} is set to {flag}")
        return flag, args

    # HACK: just get some kind of parsing for right now
    do_resume, args = check_arg("--resume", args)
    no_publish, args = check_arg("--no-publish", args)
    no_merge, args = check_arg("--no-merge", args)
    no_wait, args = check_arg("--no-wait", args)
    do_publish = not no_publish
    do_merge = not no_merge
    do_wait = not no_wait
    if do_wait:
        # want to make sure that we're going to run this with new weather
        wx_updated = False
        with locks_for([FILE_CURRENT, FILE_LATEST]):
            current = pd.read_csv(FILE_CURRENT)
            latest = pd.read_csv(FILE_LATEST)
            wx_updated = not current.equals(latest)
        while True:
            dir_model = get_model_dir_uncached(WX_MODEL)
            modelrun = os.path.basename(dir_model)
            # HACK: just trying to check if run used this weather
            prev = make_resume(do_publish=False, do_merge=False)
            wx_updated = prev._modelrun != modelrun
            if wx_updated:
                # HACK: need to set this so cache isn't used
                set_model_dir(dir_model)
                break
            logging.info(
                f"Previous run already used {modelrun} - waiting {WAIT_WX}s for updated weather"
            )
            time.sleep(WAIT_WX)
    if do_resume:
        if 1 < len(args):
            logging.fatal(f"Too many arguments:\n\t {sys.argv}")
        dir_resume = args[0] if args else None
        run = make_resume(dir_resume, do_publish=do_publish, do_merge=do_merge)
    else:
        max_days = int(args[1]) if len(args) > 1 else None
        dir_arg = args[0] if len(args) > 0 else None
        if dir_arg and not os.path.isdir(dir_arg):
            logging.fatal(f"Expected directory but got {dir_arg}")
            sys.exit(-1)
        if dir_arg and DIR_OUTPUT in os.path.abspath(dir_arg):
            if max_days:
                logging.fatal("Cannot specify number of days if resuming")
                sys.exit(-1)
            # if we give it a simulation directory then resume those sims
            run = Run(dir=dir_arg, do_publish=do_publish)
            logging.info(f"Resuming simulations in {dir_arg}")
        else:
            run = Run(
                dir_fires=dir_arg,
                max_days=max_days,
                do_publish=do_publish,
                do_merge=do_merge,
            )
    df_final = run.run_until_successful()
