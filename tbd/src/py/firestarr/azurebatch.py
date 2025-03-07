import datetime
import os
import re
import time

import azure.batch as batch
import azure.batch.batch_auth as batchauth
import azure.batch.models as batchmodels
import pandas as pd
from azurebatch_helpers import (
    STANDARD_ERROR_FILE_NAME,
    STANDARD_OUT_FILE_NAME,
    read_task_file_as_string,
)
from common import (
    CONFIG,
    DIR_OUTPUT,
    FILE_SIM_LOG,
    SECONDS_PER_MINUTE,
    locks_for,
    logging,
)
from multiprocess import Lock, Process
from redundancy import call_safe, get_stack

# from common import SECONDS_PER_MINUTE
# from multiprocess import Lock, Process
from tqdm import tqdm

FILE_LOCK_BATCH_JOB = os.path.join(DIR_OUTPUT, "batch_job")

# HACK: just get the values out of here for now
_BATCH_ACCOUNT_NAME = CONFIG.get("BATCH_ACCOUNT_NAME")
_BATCH_ACCOUNT_KEY = CONFIG.get("BATCH_ACCOUNT_KEY")
_STORAGE_ACCOUNT_NAME = CONFIG.get("STORAGE_ACCOUNT_NAME")
_STORAGE_CONTAINER = CONFIG.get("STORAGE_CONTAINER")
_STORAGE_KEY = CONFIG.get("STORAGE_KEY")
_REGISTRY_USER_NAME = CONFIG.get("REGISTRY_USER_NAME")
_REGISTRY_SERVER = f"{_REGISTRY_USER_NAME}.azurecr.io"
_REGISTRY_PASSWORD = CONFIG.get("REGISTRY_PASSWORD")
_REGISTRY_URL = f"{_REGISTRY_SERVER}/firestarr"
_CONTAINER_PY = f"{_REGISTRY_URL}/tbd_prod_stable:latest"
_CONTAINER_BIN = f"{_REGISTRY_URL}/firestarr:latest"
SSH_KEY = (
    "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQDQY2udxIHnsghQZXDXNge1RD"
    "gzu5sWkHnbad5KGCI49TrwTPwheQfApkDwOvkhkwJG0m+xts9cimeW8IfdiWjH"
    "bVe5a8SONR/cRD7uqMJHBr/rFWqM56N7AZpoPkxhbdDppC3kxocwKqn1M9miw1"
    "hYksm20MaJ2y/M/zXQajM3T7vxjQtnnppF435vnQFrrY/cgLZNr+SZVt3D4I/l"
    "9lSghi8a91PbsDCQL+kACuuWAXQWV5BYqVq/hkVz3wPhus6mlfYvz9DvtUhyth"
    "zUYcXVUUe3118Gsw+VZ2u0KRNpNqhAdRZM1VkvQUuRMDdKq/zxxvk6suO0OL3E"
    "EuGTgljKX/1LMXFgDBOEOgZAyE82wp21luuebRjX0n4wCxKFTZVhvUcs5O0W6/M"
    "cJrQ2w4y2xtrCrPYvzrQEEfqRldDP8L5hFiERGYtFZFFEg1j7d+nWsc2xhWfaFmT"
    "shW3xcJCtgmNPW1KfoO/6Frlr9/Njs+gLETXHZdGJbQ/TSKFprW0="
)


def get_container_registries():
    return [
        batchmodels.ContainerRegistry(
            user_name=_REGISTRY_USER_NAME,
            password=_REGISTRY_PASSWORD,
            # registry_server=_REGISTRY_URL,
            registry_server=_REGISTRY_SERVER,
        )
    ]


_VM_CONFIGURATION = batchmodels.VirtualMachineConfiguration(
    image_reference=batchmodels.ImageReference(
        publisher="microsoft-azure-batch",
        offer="ubuntu-server-container",
        sku="20-04-lts",
        version="latest",
    ),
    node_agent_sku_id="batch.node.ubuntu 20.04",
    container_configuration=batchmodels.ContainerConfiguration(
        type="dockerCompatible",
        container_image_names=[_CONTAINER_PY, _CONTAINER_BIN],
        container_registries=get_container_registries(),
    ),
)
# _POOL_VM_SIZE = "STANDARD_F72S_V2"
# _POOL_VM_SIZE = "STANDARD_F32S_V2"
# only running 21 streams for now so don't use 32 cores
# _POOL_VM_SIZE = "STANDARD_F16S_V2"
# # generally gets stuck on a few scenarios so scale way back until single-core performance improves for now
# _POOL_VM_SIZE = "STANDARD_F8S_V2"
_POOL_VM_SIZE = "STANDARD_F4S_V2"
POOL_ID = "pool_firestarr"
_MIN_NODES = 0
# _MIN_NODES = 1
_MAX_NODES = 50
_USE_LOW_PRIORITY = True
# _MAX_NODES = 1
# if any tasks pending but not running then want enough nodes to start
# those and keep the current ones running, but if nothing in queue then
# want to deallocate everything on completion
# nodes don't deallocate until done if currently running and we set to 0
# use low priority nodes if over max number, but they stay as spot nodes so maybe not great if getting preempted
_AUTO_SCALE_FORMULA = f"""
    $min_nodes = {_MIN_NODES};
    $max_nodes = {_MAX_NODES};
    $max_low = {_MAX_NODES if _USE_LOW_PRIORITY else 0};
    $samples = $PendingTasks.GetSamplePercent(TimeInterval_Minute);
    $pending = val($PendingTasks.GetSample(1), 0);
    $active = val($ActiveTasks.GetSample(1), 0);
    $running = val($RunningTasks.GetSample(1), 0);
    $preempted = max(0, val($PreemptedNodeCount.GetSample(5 * TimeInterval_Minute), 0));
    $dedicated = $CurrentDedicatedNodes;
    $spot = $CurrentLowPriorityNodes;
    $want_nodes = ($pending > $dedicated || $spot > 0) ? ($pending - $spot) : 0;
    $want_nodes = ($dedicated + $spot) >= $pending ? 0 : $want_nodes;
    $use_nodes = $samples < 1 ? $min_nodes : $want_nodes;
    $max_dedicated = max($min_nodes, min($max_nodes, $use_nodes));
    $TargetDedicatedNodes = min($preempted + $dedicated, $max_dedicated);
    $TargetLowPriorityNodes = max(0, min($max_low, $pending - $TargetDedicatedNodes));
    $NodeDeallocationOption = taskcompletion;
"""
_AUTO_SCALE_EVALUATION_INTERVAL = datetime.timedelta(minutes=5)
_BATCH_ACCOUNT_URL = f"https://{_BATCH_ACCOUNT_NAME}.canadacentral.batch.azure.com"
_STORAGE_ACCOUNT_URL = f"https://{_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"

RELATIVE_MOUNT_PATH = "firestarr_data"
ABSOLUTE_MOUNT_PATH = f"/mnt/batch/tasks/fsmounts/{RELATIVE_MOUNT_PATH}"
# check every 30s
TASK_SLEEP = 30

CLIENT = None


def restart_unusable_nodes(pool_id=POOL_ID, client=None):
    try:
        if client is None:
            client = get_batch_client()
        pool = client.pool.get(pool_id)
        if "active" == pool.state:
            for node in client.compute_node.list(pool_id):
                node_id = node.id
                if "unusable" == node.state:
                    try:
                        # HACK: update in case changed during loop
                        node = client.compute_node.get(pool_id, node_id)
                        if "unusable" == node.state:
                            logging.error(f"Node unusable: {node_id}")
                            client.compute_node.reboot(pool_id, node_id, node_reboot_option="terminate")
                    except batchmodels.BatchErrorException:
                        # HACK: just ignore because probably another
                        #       thread is trying to do the same thing?
                        pass
    except batchmodels.BatchErrorException:
        pass


# # FIX: really not having a good time with broken pipes
# def monitor_pool_nodes(pool_id, client=None):
# if client is None:
#     client = get_batch_client()
#     try:
#         while True:
#             restart_unusable_nodes(client=client)
#             time.sleep(POOL_MONITOR_SLEEP)
#     except KeyboardInterrupt as ex:
#         raise ex
#     except batchmodels.BatchErrorException as ex:
#         logging.warning(f"Ignoring {ex}")
#         logging.warning(get_stack(ex))


# POOL_MONITOR_THREADS = {}
# POOL_MONITOR_LOCK = Lock()
# POOL_MONITOR_SLEEP = SECONDS_PER_MINUTE // 2


# def monitor_pool(pool_id=_POOL_ID_BOTH):
#     with POOL_MONITOR_LOCK:
#         thread = POOL_MONITOR_THREADS.get(pool_id, None)
#         if thread is not None:
#             logging.warning("Terminating existing monitor")
#             thread.terminate()
#         POOL_MONITOR_THREADS[pool_id] = Process(
#             target=monitor_pool_nodes, args=[pool_id], daemon=True
#         )
#         logging.debug(f"Starting to monitor pool {pool_id}")
#         POOL_MONITOR_THREADS[pool_id].start()
#         logging.debug("Done starting pool monitor")
#     logging.debug("Done creating pool monitor")


def create_container_pool(pool_id=POOL_ID, force=False, client=None):
    if client is None:
        client = get_batch_client()
    if client.pool.exists(pool_id):
        if force:
            logging.warning("Deleting existing pool [{}]...".format(pool_id))
            client.pool.delete(pool_id)
            while client.pool.exists(pool_id):
                print(".", end="", flush=True)
                time.sleep(1)
            print("", flush=True)
        else:
            return pool_id
    logging.debug("Creating pool [{}]...".format(pool_id))
    new_pool = batch.models.PoolAddParameter(
        id=pool_id,
        virtual_machine_configuration=_VM_CONFIGURATION,
        vm_size=_POOL_VM_SIZE,
        # target_dedicated_nodes=1,
        enable_auto_scale=True,
        auto_scale_formula=_AUTO_SCALE_FORMULA,
        auto_scale_evaluation_interval=_AUTO_SCALE_EVALUATION_INTERVAL,
        mount_configuration=[
            batchmodels.MountConfiguration(
                azure_blob_file_system_configuration=(
                    batchmodels.AzureBlobFileSystemConfiguration(
                        account_name=_STORAGE_ACCOUNT_NAME,
                        container_name=_STORAGE_CONTAINER,
                        relative_mount_path=RELATIVE_MOUNT_PATH,
                        account_key=_STORAGE_KEY,
                        blobfuse_options=" ".join(
                            [
                                f"-o {arg}"
                                for arg in [
                                    "attr_timeout=240",
                                    "entry_timeout=240",
                                    "negative_timeout=120",
                                    "allow_other",
                                ]
                            ]
                        ),
                    )
                )
            ),
        ],
    )
    client.pool.add(new_pool)
    return pool_id


def make_or_get_job(pool_id=POOL_ID, job_id=None, client=None, *args, **kwargs):
    if client is None:
        client = get_batch_client()
    # # start monitoring pool for unusable nodes
    # monitor_pool(pool_id, client=client)
    with locks_for(FILE_LOCK_BATCH_JOB) as locks:
        if job_id is None:
            run_id = datetime.datetime.now().strftime("%Y%m%d%H%S")
            job_id = f"job_container_{run_id}"
        try:
            job = client.job.get(job_id)
            # delete if exists and completed
            if "completed" == job.state:
                logging.info(f"Deleting completed job {job_id}")
                client.job.delete(job_id)
                while job_exists(job_id):
                    print(".", end="", flush=True)
                    time.sleep(1)
            else:
                return job, True
        except batchmodels.BatchErrorException:
            job_existed = False
            pass
        logging.info("Creating job [{}]...".format(job_id))
        job = batch.models.JobAddParameter(
            id=job_id,
            pool_info=batch.models.PoolInformation(pool_id=pool_id),
            *args,
            **kwargs,
        )
        client.job.add(job)
        return client.job.get(job_id), False


def get_user_identity():
    return batchmodels.UserIdentity(
        auto_user=batchmodels.AutoUserSpecification(
            scope=batchmodels.AutoUserScope.pool,
            elevation_level=batchmodels.ElevationLevel.admin,
        )
    )


def add_monolithic_task(job_id, client=None):
    if client is None:
        client = get_batch_client()
    task_count = 0
    tasks = [
        batch.models.TaskAddParameter(
            id="Task{}".format(task_count),
            command_line="",
            container_settings=get_container_settings(_CONTAINER_PY, client=client),
            user_identity=get_user_identity(),
        )
    ]
    task_count += 1
    client.task.add_collection(job_id, tasks)


def schedule_job_tasks(job_id, tasks, client=None):
    if client is None:
        client = get_batch_client()
    client.task.add_collection(job_id, tasks)


def get_task_name(dir_fire):
    # return dir_fire.replace("/", "-")
    # just use group name
    return os.path.basename(dir_fire)


# def get_task_path(task_id):
#     return task_id.replace("-", "/")


def find_tasks_running(job_id, dir_fire, client=None):
    if client is None:
        client = get_batch_client()
    # no tasks if job doesn't exist
    jobs = [x.id for x in client.job.list()]
    if job_id not in jobs:
        return []
    # # HACK: want to check somewhere and this seems good enough for now
    # restart_unusable_nodes(client=client)
    task_name = get_task_name(dir_fire)
    tasks = []
    # try:
    for task in client.task.list(job_id):
        if task_name in task.id and "completed" != task.state:
            tasks.append(task.id)
    return tasks
    # except batchmodels.BatchErrorException:
    #     return False


def is_successful(obj):
    return "active" != obj.state and (
        "success" == obj.execution_info.result or "TaskEnded" == obj.execution_info.failure_info.code
    )


def is_failed(obj):
    return "completed" == obj.state and "success" != obj.execution_info.result


def check_successful(job_id, task_id=None, client=None):
    if client is None:
        client = get_batch_client()
    if task_id is not None:
        return is_successful(client.task.get(job_id, task_id))
    else:
        # check if all tasks in job are done
        for task in client.task.list(job_id):
            if not is_successful(task):
                logging.error(f"Task {task.id} not successful")
                return False
        return True


def task_exists(job_id, task_id, client=None):
    if client is None:
        client = get_batch_client()
    try:
        task = client.task.get(job_id, task_id)
        return True
    except batchmodels.BatchErrorException as ex:
        if "TaskNotFound" != ex.error.code:
            raise ex
    return False


def job_exists(job_id, client=None):
    if client is None:
        client = get_batch_client()
    try:
        job = client.job.get(job_id)
        return True
    except batchmodels.BatchErrorException as ex:
        if "JobNotFound" != ex.error.code:
            raise ex
    return False


def make_or_get_simulation_task(job_id, dir_fire, client=None):
    if client is None:
        client = get_batch_client()
    task_id = get_task_name(dir_fire)
    existed = False
    task = None
    try:
        task = client.task.get(job_id, task_id)
        existed = True
    except batchmodels.BatchErrorException as ex:
        if "TaskNotFound" != ex.error.code:
            raise ex
    if task is None:
        task = batch.models.TaskAddParameter(
            id=task_id,
            command_line="./sim.sh",
            container_settings=get_container_settings(
                _CONTAINER_BIN,
                workdir=dir_fire,
                client=client,
            ),
            user_identity=get_user_identity(),
        )
    return task, existed


def add_simulation_task(job_id, dir_fire, wait=True, client=None, mark_as_done=False):
    # def do_add_simulation_task():
    #     nonlocal client
    try:
        if client is None:
            client = get_batch_client()
        job, job_existed = make_or_get_job(job_id=job_id)
        task, task_existed = make_or_get_simulation_task(job_id, dir_fire, client=client)
        # HACK: assume jobs will never be completed without directories being correct
        if "completed" == job.state:
            if not mark_as_done:
                logging.fatal(f"Job {job_id} is completed but simulation for {dir_fire} didn't finish properly")
            else:
                return task.id
        if task_existed:
            if mark_as_done:
                # just return if no task but it's done already
                # HACK: delete since can't mark as complete without showing as failure and still requesting nodes in AutoScale
                client.task.delete(job_id, task.id)
                return None

            # HACK: since sim.sh will complete successfully without running if run already succeeded, there's no harm in running tasks again
            # if task.state not in ["active", "running"]:
            if "completed" == task.state:
                # if job_existed and "completed" == job.state:
                #     # need to not be completed to edit
                #     client.job.enable(job.id)
                logging.warning(f"Deleting completed task to rerun {dir_fire}")
                client.task.delete(job_id, task.id)
                while task_exists(job_id, task.id):
                    print(".", end="", flush=True)
                    time.sleep(1)
                # remake task so it can be added
                task, task_existed = make_or_get_simulation_task(job_id, dir_fire, client=client)
        if mark_as_done:
            # task doesn't exist so just return
            return None
        if not task_existed:
            client.task.add(job_id, task)
            # wait until task is added
            while not task_exists(job_id, task.id, client):
                time.sleep(1)
        if not check_successful(job_id, task.id, client=client):
            # need to get task again in case it was just added
            task, task_existed = make_or_get_simulation_task(job_id, dir_fire, client=client)
            # wait if requested and task isn't done
            if wait:
                while True:
                    while True:
                        task = client.task.get(job_id, task.id)
                        if "active" == task.state:
                            time.sleep(TASK_SLEEP)
                        else:
                            break
                    if "failure" == task.execution_info.result:
                        client.task.reactivate(job_id, task.id)
                    else:
                        break
        # # HACK: want to check somewhere and this seems good enough for now
        # restart_unusable_nodes(client=client)
        return task.id
    except Exception as ex:
        return ex
    # # HACK: getting SSL errors so use call_safe()
    # return call_safe(do_add_simulation_task)


def get_container_settings(container, workdir=None, client=None):
    if client is None:
        client = get_batch_client()
    if workdir is None:
        workdir = "/appl/tbd"
    return batchmodels.TaskContainerSettings(
        image_name=_CONTAINER_BIN,
        container_run_options=" ".join(
            [
                "--rm",
                "--entrypoint /bin/sh",
                f"--workdir {workdir}",
                f"-v {ABSOLUTE_MOUNT_PATH}:/appl/data",
            ]
        ),
        registry=get_container_registries()[0],
    )


def get_active(client=None, active_only=False):
    def is_active(state):
        return "active" == state if active_only else "completed" != state

    if client is None:
        client = get_batch_client()
    jobs = {j.id: j for j in client.job.list() if is_active(j.state)}

    def get_tasks_by_job(job):
        nonlocal jobs
        tasks = {}
        try:
            tasks = {t.id: t for t in client.task.list(job.id) if is_active(t.state)}
        except batchmodels.BatchErrorException as ex:
            if "JobNotFound" != ex.error.code:
                raise ex
            # job is listed as active but is invalid so need to recreate
            logging.error(f"Batch task {job.id} is listed as active but invalid")
            j = make_or_get_job(job_id=job.id)
            # HACK: replace value in outside dictionary
            jobs[j.id] = j
        return tasks

    tasks = {job.id: get_tasks_by_job(job) for job in jobs.values()}

    pools = {p.id: p for p in client.pool.list() if is_active(p.state)}
    nodes = {pool.id: {n.id: n for n in list_nodes(pool.id, client=None)} for pool in pools.values()}
    return jobs, tasks, pools, nodes


def show_active(client=None):
    if client is None:
        client = get_batch_client()
    jobs, tasks, pools, nodes = get_active(client=client)
    print(f"jobs:\n{jobs}\n\ntasks:\n{tasks}\n\npools:\n{pools}\n\nnodes:\n{nodes}\n")


def run_oneoff_task(cmd, pool_id=POOL_ID, client=None):
    if client is None:
        client = get_batch_client()
    job_id = "job_oneoff"
    # try:
    #     job = client.job.get(job_id)
    #     # logging.warning("Deleting existing job")
    #     # job = client.job.delete(job_id)
    #     # try:
    #     #     while True:
    #     #         job = client.job.get(job_id)
    #     #         if job.state == "deleting":
    #     #             print(".", end="", flush=True)
    #     #             time.sleep(1)
    #     #     print("", flush=True)
    #     # except batchmodels.BatchErrorException:
    #     #     pass
    # except batchmodels.BatchErrorException:
    #     pass
    job, job_existed = make_or_get_job(pool_id, job_id, priority=500, client=client)
    task_id = f"task_oneoff_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    task = batch.models.TaskAddParameter(
        id=task_id,
        command_line=cmd,
        container_settings=get_container_settings(_CONTAINER_PY, client=None),
        user_identity=get_user_identity(),
    )
    client.task.add(job_id, task)
    logging.info(f"Running {task.id}:\n\t{cmd}")
    if not check_successful(job_id, task_id, client=client):
        # wait if requested and task isn't done
        while True:
            task = client.task.get(job_id, task_id)
            if "active" != task.state:
                break
            print(".", end="", flush=True)
            time.sleep(1)
        print("", flush=True)
    return task.id


def show_result(job_id=None, task_id=None):
    if job_id is None or task_id is None:
        t = list_nodes()[0].as_dict()["recent_tasks"][-1]
        job_id = t["job_id"]
        task_id = t["task_id"]
    for f in [STANDARD_OUT_FILE_NAME, STANDARD_ERROR_FILE_NAME]:
        file = client.file.get_from_task(job_id, task_id, f)
        print("".join([str(x) for x in file]))


def wait_for_tasks_to_complete(job_id, client=None):
    if client is None:
        client = get_batch_client()
    tasks = [x for x in client.task.list(job_id)]
    left = len(tasks)
    prev = left
    with tqdm(desc="Waiting for tasks", total=len(tasks)) as tq:
        while left > 0:
            # does this update or do we need to get them again?
            incomplete_tasks = [task for task in tasks if task.state != batchmodels.TaskState.completed]
            left = len(incomplete_tasks)
            tq.update(prev - left)
            prev = left
            print(".", end="", flush=True)
            time.sleep(1)
            tasks = client.task.list(job_id)
        print("", flush=True)


def have_batch_config():
    return _BATCH_ACCOUNT_NAME and _BATCH_ACCOUNT_KEY


def get_batch_client():
    global CLIENT
    if not have_batch_config():
        return None
    if CLIENT is None:
        CLIENT = batch.BatchServiceClient(
            batchauth.SharedKeyCredentials(_BATCH_ACCOUNT_NAME, _BATCH_ACCOUNT_KEY),
            batch_url=_BATCH_ACCOUNT_URL,
        )
        # HACK:
        # first load so use get_active() to force checking if jobs are valid
        jobs, tasks, pools, nodes = get_active(client=CLIENT)
    return CLIENT


def is_running_on_azure():
    # HACK: shell isn't set when ssh into node, but AZ_BATCH_POOL_ID is only in tasks?
    return (
        not CONFIG.get("FORCE_LOCAL_TASKS", False)
        and os.environ.get("AZ_BATCH_POOL_ID", None) == POOL_ID
        or not os.environ.get("SHELL", False)
    )


def cancel_active_jobs(client=None):
    if client is None:
        client = get_batch_client()
    active = [x for x in client.job.list() if x.state == "active"]
    for j in active:
        print(j.id)
        client.job.terminate(j.id)


def get_job_schedules(client=None):
    if client is None:
        client = get_batch_client()
    return [x for x in client.job_schedule.list()]


def deactivate_job_schedules(client=None):
    if client is None:
        client = get_batch_client()
    active = [x for x in client.job_schedule.list() if x.state == "active"]
    for s in active:
        print(s.id)
        client.job_schedule.disable(s.id)


def list_nodes(pool_id=POOL_ID, client=None):
    if client is None:
        client = get_batch_client()
    return [x for x in client.compute_node.list(pool_id)]


def make_schedule(pool_id=POOL_ID, client=None):
    if client is None:
        client = get_batch_client()
    job_schedule_id = f"schedule_check_{pool_id}"
    if client.job_schedule.exists(job_schedule_id):
        logging.warning(f"Deleting existing {job_schedule_id}")
        client.job_schedule.delete(job_schedule_id)
        while client.job_schedule.exists(job_schedule_id):
            print(".", end="", flush=True)
            time.sleep(1)
        print("", flush=True)
    schedule = batchmodels.JobScheduleAddParameter(
        id=job_schedule_id,
        schedule=batchmodels.Schedule(
            recurrence_interval="PT1H",
            do_not_run_until=(pd.to_datetime(datetime.date.today(), utc=True) + datetime.timedelta(days=1, hours=4)),
        ),
        job_specification=batchmodels.JobSpecification(
            pool_info=batchmodels.PoolInformation(pool_id=pool_id),
            job_manager_task=batchmodels.JobManagerTask(
                id=f"{job_schedule_id}_manager",
                required_slots=1,
                kill_job_on_completion=True,
                user_identity=get_user_identity(),
                allow_low_priority_node=False,
                command_line="/appl/tbd/scripts/lock_run.sh",
                container_settings=get_container_settings(_CONTAINER_PY, client=client),
            ),
            constraints=batchmodels.JobConstraints(max_task_retry_count=0),
        ),
    )
    client.job_schedule.add(schedule)
    return job_schedule_id


def update_registry(pool_id, client=None):
    if client is None:
        client = get_batch_client()
    pool = client.pool.get(pool_id)
    client.pool.patch(
        pool_id,
        batchmodels.PoolPatchParameter(
            virtual_machine_configuration=_VM_CONFIGURATION,
        ),
    )


def last_task(client=CLIENT):
    if client is None:
        client = get_batch_client()
    t = list_nodes()[0].as_dict()["recent_tasks"][-1]
    return client.task.get(t["job_id"], t["task_id"])


def last_failure(client=None):
    if client is None:
        client = get_batch_client()
    t = last_task(client)
    return t.as_dict()["execution_info"]["failure_info"]


def get_login(pool_id=POOL_ID, client=None, node=0):
    if client is None:
        client = get_batch_client()
    node_id = list_nodes()[node].as_dict()["id"]
    # try:
    #     client.compute_node.delete_user(pool_id, node_id, "user")
    # except batchmodels.BatchErrorException:
    #     pass
    user = "user"
    try:
        print(f"Trying to add user {user}")
        client.compute_node.add_user(
            pool_id,
            node_id,
            batchmodels.ComputeNodeUser(name=user, is_admin=True, ssh_public_key=SSH_KEY),
        )
    except batchmodels.BatchErrorException:
        client.compute_node.update_user(
            pool_id,
            node_id,
            user,
            node_update_user_parameter=batchmodels.NodeUpdateUserParameter(
                ssh_public_key=SSH_KEY,
                expiry_time=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
            ),
        )
    s = client.compute_node.get_remote_login_settings(
        pool_id,
        node_id,
    )
    cmd = "sudo /mnt/batch/tasks/fsmounts/firestarr_data/container/run_docker_bash.sh"
    print(f"ssh -ti ~/.ssh/id_azure -p {s.remote_login_port} {user}@{s.remote_login_ip_address} {cmd}")


def job_from_task(task):
    # HACK: can't find a way to do this with api
    job_id = re.match(".*/jobs/([^/]*)/tasks/.*", task.url).groups()[0]
    return client.job.get(job_id)


def evaluate_autoscale(pool_id=POOL_ID, client=None, print_result=True):
    if client is None:
        client = get_batch_client()
    r = client.pool.evaluate_auto_scale(pool_id, _AUTO_SCALE_FORMULA)
    r = r.results.replace(";", ";\n").replace("=", " = ")
    if print_result:
        print(r)
    else:
        return r


def enable_autoscale(pool_id=POOL_ID, client=None):
    if client is None:
        client = get_batch_client()
    client.pool.enable_auto_scale(
        pool_id,
        auto_scale_formula=_AUTO_SCALE_FORMULA,
        auto_scale_evaluation_interval=_AUTO_SCALE_EVALUATION_INTERVAL,
    )
    evaluate_autoscale(pool_id=pool_id, client=client)


# def get_log(task):
#     return os.path.join(get_task_path(task.id), FILE_SIM_LOG)


# def read_log(task):
#     # NOTE: since log is being written to while running, blob container can't see it yet
#     lines = None
#     if "running" == task.state:
#         job = job_from_task(task)
#         txt = read_task_file_as_string(client, job.id, task.id, STANDARD_OUT_FILE_NAME)
#         lines = txt.split("\n")
#     else:
#         file_log = get_log(task)
#         with open(file_log) as f:
#             lines = f.readlines()
#     return lines


if __name__ == "__main__":
    client = get_batch_client()
    # pool_id = create_container_pool()
    # print(get_login())
    # pool_id = create_container_pool(force=True)
    # run_oneoff_task("echo test >> /appl/data/testoneoff")
    # run_oneoff_task("/appl/tbd/scripts/force_run.sh")
    # job_schedule_id = make_schedule(POOL_ID)
    # jobs, tasks, pools, nodes = get_active()
