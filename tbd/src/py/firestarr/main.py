import os
import sys

from common import DEFAULT_FILE_LOG_LEVEL, DIR_LOG, DIR_OUTPUT, logging
from log import add_log_rotating
from simulation import Run, make_resume

LOG_MAIN = add_log_rotating(
    os.path.join(DIR_LOG, "firestarr.log"), level=DEFAULT_FILE_LOG_LEVEL
)
logging.info("Starting main.py")


sys.path.append(os.path.dirname(sys.executable))
sys.path.append("/usr/local/bin")

if __name__ == "__main__":
    logging.info("Called with args %s", str(sys.argv))
    if "--resume" in sys.argv:
        dir_resume = sys.argv[2] if 3 <= len(sys.argv) else None
        run = make_resume(dir_resume)
    else:
        max_days = int(sys.argv[2]) if len(sys.argv) > 2 else None
        dir_arg = sys.argv[1] if len(sys.argv) > 1 else None
        do_publish = True
        if dir_arg and DIR_OUTPUT in os.path.abspath(dir_arg):
            if max_days:
                logging.fatal("Cannot specify number of days if resuming")
                sys.exit(-1)
            # if we give it a simulation directory then resume those sims
            run = Run(dir=dir_arg, do_publish=do_publish)
            logging.info(f"Resuming simulations in {dir_arg}")
        else:
            run = Run(dir_fires=dir_arg, max_days=max_days, do_publish=do_publish)
    results, dates_out, total_time = run.process()
