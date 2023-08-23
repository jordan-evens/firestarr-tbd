import datetime
import os
import time

import azure.batch as batch
import azure.batch.batch_auth as batchauth
import azure.batch.models as batchmodels
from common import CONFIG, SECONDS_PER_MINUTE, logging
from multiprocess import Lock, Process
from redundancy import get_stack

# from common import SECONDS_PER_MINUTE
# from multiprocess import Lock, Process
from tqdm import tqdm

# HACK: just get the values out of here for now
_BATCH_ACCOUNT_NAME = CONFIG.get("BATCH_ACCOUNT_NAME")
_BATCH_ACCOUNT_KEY = CONFIG.get("BATCH_ACCOUNT_KEY")
_STORAGE_ACCOUNT_NAME = CONFIG.get("STORAGE_ACCOUNT_NAME")
_STORAGE_CONTAINER = CONFIG.get("STORAGE_CONTAINER")
_STORAGE_KEY = CONFIG.get("STORAGE_KEY")
_REGISTRY_SERVER = CONFIG.get("REGISTRY_SERVER")
_REGISTRY_USER_NAME = CONFIG.get("REGISTRY_USER_NAME")
_REGISTRY_PASSWORD = CONFIG.get("REGISTRY_PASSWORD")
_REGISTRY_URL = CONFIG.get("REGISTRY_URL")
_CONTAINER_PY = f"{_REGISTRY_URL}/tbd_prod_stable:latest"
_CONTAINER_BIN = f"{_REGISTRY_URL}/firestarr:latest"

_POOL_VM_SIZE = "STANDARD_F72S_V2"
# _POOL_VM_SIZE = "STANDARD_F32S_V2"
POOL_ID = "pool_firestarr_dev"
_MIN_NODES = 1
_MAX_NODES = 1
# _MAX_NODES = 1
# if any tasks pending but not running then want enough nodes to start
# those and keep the current ones running, but if nothing in queue then
# want to deallocate everything on completion
_AUTO_SCALE_FORMULA = "\n".join(
    [
        f"$min_nodes = {_MIN_NODES};",
        f"$max_nodes = {_MAX_NODES};",
        "$samples = $PendingTasks.GetSamplePercent(TimeInterval_Minute);",
        "$pending = val($PendingTasks.GetSample(1), 0);",
        "$want_nodes = val($ActiveTasks.GetSample(1), 0) > 0 ? $pending : 0;",
        "$use_nodes = $samples < 1 ? 0 : $want_nodes;",
        "$TargetDedicatedNodes = max($min_nodes, min($max_nodes, $use_nodes));",
        "$NodeDeallocationOption = taskcompletion;",
    ]
)
_AUTO_SCALE_EVALUATION_INTERVAL = datetime.timedelta(minutes=5)
_BATCH_ACCOUNT_URL = f"https://{_BATCH_ACCOUNT_NAME}.canadacentral.batch.azure.com"
_STORAGE_ACCOUNT_URL = f"https://{_STORAGE_ACCOUNT_NAME}.blob.core.windows.net"

RELATIVE_MOUNT_PATH = "firestarr_data"
ABSOLUTE_MOUNT_PATH = f"/mnt/batch/tasks/fsmounts/{RELATIVE_MOUNT_PATH}"
TASK_SLEEP = 5


def restart_unusable_nodes(batch_client=None, pool_id=POOL_ID):
    try:
        if batch_client is None:
            batch_client = get_batch_client()
        pool = batch_client.pool.get(pool_id)
        if "active" == pool.state:
            for node in batch_client.compute_node.list(pool_id):
                node_id = node.id
                if "unusable" == node.state:
                    try:
                        # HACK: update in case changed during loop
                        node = batch_client.compute_node.get(pool_id, node_id)
                        if "unusable" == node.state:
                            batch_client.compute_node.reboot(
                                pool_id, node_id, node_reboot_option="terminate"
                            )
                    except batchmodels.BatchErrorException:
                        # HACK: just ignore because probably another
                        #       thread is trying to do the same thing?
                        pass
    except batchmodels.BatchErrorException:
        pass


# # FIX: really not having a good time with broken pipes
# def monitor_pool_nodes(batch_client, pool_id):
#     try:
#         while True:
#             restart_unusable_nodes(batch_client)
#             time.sleep(POOL_MONITOR_SLEEP)
#     except KeyboardInterrupt as ex:
#         raise ex
#     except batchmodels.BatchErrorException as ex:
#         logging.warning(f"Ignoring {ex}")
#         logging.warning(get_stack(ex))


# POOL_MONITOR_THREADS = {}
# POOL_MONITOR_LOCK = Lock()
# POOL_MONITOR_SLEEP = SECONDS_PER_MINUTE // 2


# def monitor_pool(batch_client, pool_id=_POOL_ID_BOTH):
#     with POOL_MONITOR_LOCK:
#         thread = POOL_MONITOR_THREADS.get(pool_id, None)
#         if thread is not None:
#             logging.warning("Terminating existing monitor")
#             thread.terminate()
#         POOL_MONITOR_THREADS[pool_id] = Process(
#             target=monitor_pool_nodes, args=[batch_client, pool_id], daemon=True
#         )
#         logging.debug(f"Starting to monitor pool {pool_id}")
#         POOL_MONITOR_THREADS[pool_id].start()
#         logging.debug("Done starting pool monitor")
#     logging.debug("Done creating pool monitor")


def create_container_pool(batch_client, pool_id=POOL_ID, force=False):
    if batch_client.pool.exists(pool_id):
        if force:
            logging.warning("Deleting existing pool [{}]...".format(pool_id))
            batch_client.pool.delete(pool_id)
            while batch_client.pool.exists(pool_id):
                time.sleep(10)
        else:
            return pool_id
    logging.debug("Creating pool [{}]...".format(pool_id))
    new_pool = batch.models.PoolAddParameter(
        id=pool_id,
        virtual_machine_configuration=batchmodels.VirtualMachineConfiguration(
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
        ),
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
    batch_client.pool.add(new_pool)
    return pool_id


def make_or_get_job(batch_client, pool_id=POOL_ID, job_id=None, *args, **kwargs):
    # # start monitoring pool for unusable nodes
    # monitor_pool(batch_client, pool_id)
    if job_id is None:
        run_id = datetime.datetime.now().strftime("%Y%m%d%H%S")
        job_id = f"job_container_{run_id}"
    try:
        job = batch_client.job.get(job_id)
        # delete if exists and completed
        if "completed" == job.state:
            logging.info(f"Deleting completed job {job_id}")
            batch_client.job.delete(job_id)
        else:
            return job_id
    except batchmodels.BatchErrorException:
        pass
    logging.info("Creating job [{}]...".format(job_id))
    job = batch.models.JobAddParameter(
        id=job_id,
        pool_info=batch.models.PoolInformation(pool_id=pool_id),
        *args,
        **kwargs,
    )
    batch_client.job.add(job)
    return job_id


def get_user_identity():
    return (
        batchmodels.UserIdentity(
            auto_user=batchmodels.AutoUserSpecification(
                scope=batchmodels.AutoUserScope.pool,
                elevation_level=batchmodels.ElevationLevel.admin,
            )
        ),
    )


def add_monolithic_task(batch_client, job_id):
    task_count = 0
    tasks = list()
    tasks.append(
        batch.models.TaskAddParameter(
            id="Task{}".format(task_count),
            command_line="",
            container_settings=get_container_settings(batch_client, _CONTAINER_PY),
            user_identity=get_user_identity(),
        )
    )
    task_count += 1
    batch_client.task.add_collection(job_id, tasks)


def get_task_name(dir_fire):
    return dir_fire.replace("/", "-")


def find_tasks_running(batch_client, job_id, dir_fire):
    # HACK: want to check somewhere and this seems good enough for now
    restart_unusable_nodes(batch_client)
    task_name = get_task_name(dir_fire)
    tasks = []
    # try:
    for task in batch_client.task.list(job_id):
        if task_name in task.id and "completed" != task.state:
            tasks.append(task.id.replace("-", "/"))
    return tasks
    # except batchmodels.BatchErrorException:
    #     return False


def is_successful(obj):
    return "active" != obj.state and "success" == obj.execution_info.result


def is_failed(obj):
    return "completed" == obj.state and "success" != obj.execution_info.result


def check_successful(batch_client, job_id, task_id=None):
    if task_id is not None:
        return is_successful(batch_client.task.get(job_id, task_id))
    else:
        # check if all tasks in job are done
        for task in batch_client.task.list(job_id):
            if not is_successful(task):
                logging.error(f"Task {task.id} not successful")
                return False
        return True


def make_or_get_simulation_task(batch_client, job_id, dir_fire):
    task_id = get_task_name(dir_fire)
    existed = False
    task = None
    try:
        task = batch_client.task.get(job_id, task_id)
        existed = True
    except batchmodels.BatchErrorException as ex:
        if "TaskNotFound" != ex.error.code:
            raise ex
    if task is None:
        task = batch.models.TaskAddParameter(
            id=task_id,
            command_line="./sim.sh",
            container_settings=get_container_settings(
                batch_client, _CONTAINER_BIN, workdir=dir_fire
            ),
            user_identity=get_user_identity(),
        )
    return task, existed


def add_simulation_task(batch_client, job_id, dir_fire, wait=True):
    task, existed = make_or_get_simulation_task(batch_client, job_id, dir_fire)
    if not existed:
        batch_client.task.add(job_id, task)
    if not check_successful(batch_client, job_id, task.id):
        # wait if requested and task isn't done
        if wait:
            while True:
                while True:
                    task = batch_client.task.get(job_id, task.id)
                    if "active" == task.state:
                        time.sleep(TASK_SLEEP)
                    else:
                        break
                if "failure" == task.execution_info.result:
                    batch_client.task.reactivate(job_id, task.id)
                else:
                    break
    # # HACK: want to check somewhere and this seems good enough for now
    # restart_unusable_nodes(batch_client)
    return task.id


def get_container_registries():
    return [
        batchmodels.ContainerRegistry(
            user_name=_REGISTRY_USER_NAME,
            password=_REGISTRY_PASSWORD,
            registry_server=_REGISTRY_SERVER,
        )
    ]


def get_container_settings(batch_client, container, workdir=None):
    if workdir is None:
        workdir = "/appl/tbd"
    return (
        batchmodels.TaskContainerSettings(
            image_name=_CONTAINER_BIN,
            container_run_options=" ".join(
                [
                    "--rm",
                    "--entrypoint /bin/sh",
                    f"--workdir {workdir}",
                    f"-v {ABSOLUTE_MOUNT_PATH}:/appl/data",
                ]
            ),
            container_registries=get_container_registries(),
        ),
    )


def run_oneoff_task(batch_client, cmd, pool_id=POOL_ID):
    job_id = "tasks_oneoff"
    job = make_or_get_job(batch_client, pool_id, job_id, priority=500)
    task_id = f"task_oneoff_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    task = batch.models.TaskAddParameter(
        id=task_id,
        command_line=cmd,
        container_settings=get_container_settings(batch_client, _CONTAINER_BIN),
        user_identity=get_user_identity(),
    )
    batch_client.task.add(job_id, task)
    logging.info("Running {task.id}:\n\t{cmd}")
    if not check_successful(batch_client, job_id, task.id):
        # wait if requested and task isn't done
        while True:
            task = batch_client.task.get(job_id, task.id)
            if "active" == task.state:
                time.sleep(TASK_SLEEP)
    return task.id


def wait_for_tasks_to_complete(batch_client, job_id):
    tasks = [x for x in batch_client.task.list(job_id)]
    left = len(tasks)
    prev = left
    with tqdm(desc="Waiting for tasks", total=len(tasks)) as tq:
        while left > 0:
            # does this update or do we need to get them again?
            incomplete_tasks = [
                task for task in tasks if task.state != batchmodels.TaskState.completed
            ]
            left = len(incomplete_tasks)
            tq.update(prev - left)
            prev = left
            time.sleep(1)
            tasks = batch_client.task.list(job_id)


def have_batch_config():
    return _BATCH_ACCOUNT_NAME and _BATCH_ACCOUNT_KEY


def get_batch_client():
    if not have_batch_config():
        return None
    return batch.BatchServiceClient(
        batchauth.SharedKeyCredentials(_BATCH_ACCOUNT_NAME, _BATCH_ACCOUNT_KEY),
        batch_url=_BATCH_ACCOUNT_URL,
    )


def is_running_on_azure():
    # HACK: shell isn't set when ssh into node, but AZ_BATCH_POOL_ID is only in tasks?
    return (
        not CONFIG.get("FORCE_LOCAL_TASKS", False)
        and os.environ.get("AZ_BATCH_POOL_ID", None) == POOL_ID
        or not os.environ.get("SHELL", False)
    )


def cancel_active_jobs(batch_client):
    active = [x for x in batch_client.job.list() if x.state == "active"]
    for j in active:
        print(j.id)
        batch_client.job.terminate(j.id)


def get_job_schedules(batch_client):
    return [x for x in batch_client.job_schedule.list()]


def deactivate_job_schedules(batch_client):
    active = [x for x in batch_client.job_schedule.list() if x.state == "active"]
    for s in active:
        print(s.id)
        batch_client.job_schedule.disable(s.id)


def list_nodes(batch_client, pool_id=POOL_ID):
    return [x for x in batch_client.compute_node.list(pool_id)]


def make_schedule(batch_client, pool_id=POOL_ID):
    batch_client.job_schedule.add(
        batchmodels.JobScheduleAddParameter(
            id=f"schedule_check_{pool_id}",
            schedule=batchmodels.Schedule(recurrence_interval="PT1H"),
            job_specification=batchmodels.JobSpecification(
                pool_info=batchmodels.PoolInformation(pool_id=pool_id),
                job_manager_task=batchmodels.JobManagerTask(
                    id=f"{job_schedule_id}_manager",
                    required_slots=1,
                    kill_job_on_completion=True,
                    user_identity=get_user_identity(),
                    allow_low_priority_node=False,
                    command_line="/appl/tbd/scripts/force_run.sh",
                    container_settings=get_container_settings(
                        batch_client, _CONTAINER_PY
                    ),
                ),
                constraints=batchmodels.TaskConstraints(
                    retention_time="P7D", max_task_retry_count=-1
                ),
            ),
        )
    )


if __name__ == "__main__":
    batch_client = get_batch_client()
    job_schedule_id = make_schedule(batch_client, POOL_ID)
    pool_id = create_container_pool(batch_client)
    # pool_id = create_container_pool(batch_client, force=True)
