import os
import sys

from common import DEFAULT_FILE_LOG_LEVEL, DIR_LOG, DIR_OUTPUT, MAX_NUM_DAYS, logging
from log import add_log_rotating
from simulation import Run, resume

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
        resume(dir_resume)
    else:
        max_days = int(sys.argv[1]) if len(sys.argv) > 1 else MAX_NUM_DAYS
        dir_fires = sys.argv[2] if len(sys.argv) > 2 else None
        if dir_fires and DIR_OUTPUT in os.path.abspath(dir_fires):
            run = Run(dir=dir_fires)
            # if we give it a simulation directory then resume those sims
            logging.info(f"Resuming simulations in {dir_fires}")
            (
                dir_out,
                dir_current,
                results,
                dates_out,
                total_time,
            ) = run.run_fires_in_dir_by_priority()
        else:
            run = Run(dir_fires=dir_fires)
            dir_out, dir_current, results, dates_out, total_time = run.run_all_fires(
                max_days, do_publish=True
            )
        # simtimes, total_time, dates = run_all_fires()
        # dir_root = "/appl/data/output/current_m3"
