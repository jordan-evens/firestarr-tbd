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
    do_publish = not no_publish
    if do_resume:
        if 1 < len(args):
            logging.fatal(f"Too many arguments:\n\t {sys.argv}")
        dir_resume = args[0] if args else None
        run = make_resume(dir_resume, do_publish=do_publish)
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
            run = Run(dir_fires=dir_arg, max_days=max_days, do_publish=do_publish)
    results, dates_out, total_time = run.process()
