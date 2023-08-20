import datetime
import time

import azure.batch as batch
import azure.batch.batch_auth as batchauth
import azure.batch.models as batchmodels
import azurebatch.config as config
from tqdm import tqdm

RELATIVE_MOUNT_PATH = "firestarr_data"


def create_container_pool(batch_client, pool_id=config._POOL_ID_BOTH, force=False):
    if batch_client.pool.exists(pool_id):
        if force:
            print("Deleting existing pool [{}]...".format(pool_id))
            batch_client.pool.delete(pool_id)
        else:
            return
    print("Creating pool [{}]...".format(pool_id))
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
                container_image_names=[config._CONTAINER_PY, config._CONTAINER_BIN],
                container_registries=[
                    batchmodels.ContainerRegistry(
                        user_name=config._REGISTRY_USER_NAME,
                        password=config._REGISTRY_PASSWORD,
                        registry_server=config._REGISTRY_SERVER,
                    )
                ],
            ),
        ),
        vm_size=config._POOL_VM_SIZE,
        # target_dedicated_nodes=1,
        enable_auto_scale=True,
        auto_scale_formula=config._AUTO_SCALE_FORMULA,
        auto_scale_evaluation_interval=config._AUTO_SCALE_EVALUATION_INTERVAL,
        mount_configuration=[
            batchmodels.MountConfiguration(
                azure_blob_file_system_configuration=(
                    batchmodels.AzureBlobFileSystemConfiguration(
                        account_name=config._STORAGE_ACCOUNT_NAME,
                        container_name=config._STORAGE_CONTAINER,
                        relative_mount_path=RELATIVE_MOUNT_PATH,
                        account_key=config._STORAGE_KEY,
                        blobfuse_options="-o attr_timeout=240 -o entry_timeout=240 -o negative_timeout=120 -o allow_other",
                    )
                )
                # azure_blob_file_system_configuration=(
                #     batchmodels.AzureBlobFileSystemConfiguration(
                #         account_name=config._STORAGE_ACCOUNT_NAME,
                #         container_name=config._STORAGE_CONTAINER,
                #         relative_mount_path=_RELATIVE_MOUNT_PATH,
                #         account_key=config._STORAGE_KEY,
                #         blobfuse_options="-o allow_other",
                #     )
                # )
            ),
        ],
    )
    batch_client.pool.add(new_pool)
    return pool_id


# def create_container_pool(batch_client, pool_id=config._POOL_ID_PY, force=False):
#     if batch_client.pool.exists(pool_id):
#         if force:
#             print("Deleting existing pool [{}]...".format(pool_id))
#             batch_client.pool.delete(pool_id)
#         else:
#             return
#     print("Creating pool [{}]...".format(pool_id))
#     new_pool = batch.models.PoolAddParameter(
#         id=pool_id,
#         virtual_machine_configuration=batchmodels.VirtualMachineConfiguration(
#             image_reference=batchmodels.ImageReference(
#                 publisher="microsoft-azure-batch",
#                 offer="ubuntu-server-container",
#                 sku="20-04-lts",
#                 version="latest",
#             ),
#             node_agent_sku_id="batch.node.ubuntu 20.04",
#             container_configuration=batchmodels.ContainerConfiguration(
#                 type="dockerCompatible",
#                 container_image_names=[config._CONTAINER],
#                 container_registries=[
#                     batchmodels.ContainerRegistry(
#                         user_name=config._REGISTRY_USER_NAME,
#                         password=config._REGISTRY_PASSWORD,
#                         registry_server=config._REGISTRY_SERVER,
#                     )
#                 ],
#             ),
#         ),
#         vm_size=config._POOL_VM_SIZE,
#         # target_dedicated_nodes=1,
#         enable_auto_scale=True,
#         auto_scale_formula=config._AUTO_SCALE_FORMULA,
#         auto_scale_evaluation_interval=config._AUTO_SCALE_EVALUATION_INTERVAL,
#         mount_configuration=[
#             batchmodels.MountConfiguration(
#                 azure_blob_file_system_configuration=(
#                     batchmodels.AzureBlobFileSystemConfiguration(
#                         account_name=config._STORAGE_ACCOUNT_NAME,
#                         container_name=config._STORAGE_CONTAINER,
#                         relative_mount_path=_RELATIVE_MOUNT_PATH,
#                         account_key=config._STORAGE_KEY,
#                         blobfuse_options="-o attr_timeout=240 -o entry_timeout=240 -o negative_timeout=120 -o allow_other",
#                     )
#                 )
#                 # azure_blob_file_system_configuration=(
#                 #     batchmodels.AzureBlobFileSystemConfiguration(
#                 #         account_name=config._STORAGE_ACCOUNT_NAME,
#                 #         container_name=config._STORAGE_CONTAINER,
#                 #         relative_mount_path=_RELATIVE_MOUNT_PATH,
#                 #         account_key=config._STORAGE_KEY,
#                 #         blobfuse_options="-o allow_other",
#                 #     )
#                 # )
#             ),
#         ],
#     )
#     batch_client.pool.add(new_pool)
#     return pool_id


# def create_firestarr_pool(batch_client, pool_id=config._POOL_ID_BIN, force=False):
#     if batch_client.pool.exists(pool_id):
#         if force:
#             print("Deleting existing pool [{}]...".format(pool_id))
#             batch_client.pool.delete(pool_id)
#         else:
#             return
#     print("Creating pool [{}]...".format(pool_id))
#     new_pool = batch.models.PoolAddParameter(
#         id=pool_id,
#         virtual_machine_configuration=batchmodels.VirtualMachineConfiguration(
#             image_reference=batchmodels.ImageReference(
#                 publisher="microsoft-azure-batch",
#                 offer="ubuntu-server-container",
#                 sku="20-04-lts",
#                 version="latest",
#             ),
#             node_agent_sku_id="batch.node.ubuntu 20.04",
#             container_configuration=batchmodels.ContainerConfiguration(
#                 type="dockerCompatible",
#                 container_image_names=[config._CONTAINER],
#                 container_registries=[
#                     batchmodels.ContainerRegistry(
#                         user_name=config._REGISTRY_USER_NAME,
#                         password=config._REGISTRY_PASSWORD,
#                         registry_server=config._REGISTRY_SERVER,
#                     )
#                 ],
#             ),
#         ),
#         vm_size=config._POOL_VM_SIZE,
#         # target_dedicated_nodes=1,
#         enable_auto_scale=True,
#         auto_scale_formula=config._AUTO_SCALE_FORMULA,
#         auto_scale_evaluation_interval=config._AUTO_SCALE_EVALUATION_INTERVAL,
#         mount_configuration=[
#             batchmodels.MountConfiguration(
#                     batchmodels.AzureBlobFileSystemConfiguration(
#                         account_name=config._STORAGE_ACCOUNT_NAME,
#                         container_name=config._STORAGE_CONTAINER,
#                         relative_mount_path=_RELATIVE_MOUNT_PATH,
#                         account_key=config._STORAGE_KEY,
#                         blobfuse_options="-o attr_timeout=240 -o entry_timeout=240 -o negative_timeout=120 -o allow_other",
#                     )
#                 )
#                 # azure_blob_file_system_configuration=(
#                 #     batchmodels.AzureBlobFileSystemConfiguration(
#                 #         account_name=config._STORAGE_ACCOUNT_NAME,
#                 #         container_name=config._STORAGE_CONTAINER,
#                 #         relative_mount_path=_RELATIVE_MOUNT_PATH,
#                 #         account_key=config._STORAGE_KEY,
#                 #         blobfuse_options="-o allow_other",
#                 #     )
#                 # )
#             ),
#         ],
#     )
#     batch_client.pool.add(new_pool)


def add_job(batch_client, pool_id=config._POOL_ID_BOTH, job_id=None):
    if job_id is None:
        run_id = datetime.datetime.now().strftime("%Y%m%d%H%S")
        job_id = f"job_container_{run_id}"
    try:
        job = batch_client.job.get(job_id)
        # delete if exists and completed
        if "completed" == job.state:
            print(f"Deleting completed job {job_id}")
            batch_client.job.delete(job_id)
        else:
            return job_id
    except batchmodels.BatchErrorException:
        pass
    print("Creating job [{}]...".format(job_id))
    job = batch.models.JobAddParameter(
        id=job_id, pool_info=batch.models.PoolInformation(pool_id=pool_id)
    )
    batch_client.job.add(job)
    return job_id


def add_monolithic_task(batch_client, job_id):
    task_count = 0
    tasks = list()
    tasks.append(
        batch.models.TaskAddParameter(
            id="Task{}".format(task_count),
            command_line="",
            container_settings=batchmodels.TaskContainerSettings(
                image_name=config._CONTAINER_PY,
                container_run_options=" ".join(
                    [
                        # "--rm",
                        # "--name=tbd_prod_stable",
                        "--workdir /appl/tbd",
                        f"-v /mnt/batch/tasks/fsmounts/{RELATIVE_MOUNT_PATH}:/appl/data",
                    ]
                ),
            ),
            registry=batchmodels.ContainerRegistry(
                user_name=config._REGISTRY_USER_NAME,
                password=config._REGISTRY_PASSWORD,
                registry_server=config._REGISTRY_SERVER,
            ),
            user_identity=batchmodels.UserIdentity(
                auto_user=batchmodels.AutoUserSpecification(
                    scope=batchmodels.AutoUserScope.pool,
                    elevation_level=batchmodels.ElevationLevel.admin,
                )
            ),
        )
    )
    task_count += 1
    batch_client.task.add_collection(job_id, tasks)


# def add_simulation_task(batch_client, job_id, dir_fire):
#     task_id = f"Task_{os.path.basename(dir_fire)}"
#     tasks = list()
#     tasks.append(
#         batch.models.TaskAddParameter(
#             id=task_id,
#             # command_line=f"/bin/bash -c 'cd {dir_fire} && ./sim.sh'",
#             # command_line=f"{dir_fire}/sim.sh",
#             command_line=f"./sim.sh",
#             # command_line=f"""-c 'cd {dir_fire} && ./sim.sh' """,
#             container_settings=batchmodels.TaskContainerSettings(
#                 image_name=config._CONTAINER,
#                 container_run_options=" ".join(
#                     [
#                         # f"--entrypoint=\"/bin/bash -c 'cd {dir_fire} && ./sim.sh'\"",
#                         # "--entrypoint /bin/bash",
#                         "--entrypoint /bin/sh",
#                         f"--workdir {dir_fire}",
#                         # "--entrypoint ./sim.sh",
#                         # f"--workdir /appl/tbd",
#                         f"-v /mnt/batch/tasks/fsmounts/{_RELATIVE_MOUNT_PATH}:/appl/data",
#                     ]
#                 ),
#             ),
#             user_identity=batchmodels.UserIdentity(
#                 auto_user=batchmodels.AutoUserSpecification(
#                     scope=batchmodels.AutoUserScope.pool,
#                     elevation_level=batchmodels.ElevationLevel.admin,
#                 )
#             ),
#         )
#     )
#     batch_client.task.add_collection(job_id, tasks)
#     return task_id


def get_task_name(dir_fire):
    return dir_fire.replace("/", "-")


def find_tasks_running(batch_client, job_id, dir_fire):
    task_name = get_task_name(dir_fire)
    tasks = []
    try:
        for task in batch_client.task.list(job_id):
            if task_name in task.id and "completed" != task.state:
                tasks.append(task.id.replace("-", "/"))
        return tasks
    except batchmodels.BatchErrorException:
        return False


def add_simulation_task(batch_client, job_id, dir_fire):
    task_id = get_task_name(dir_fire)
    tasks = list()
    tasks.append(
        batch.models.TaskAddParameter(
            id=task_id,
            # command_line=f"/bin/bash -c 'cd {dir_fire} && ./sim.sh'",
            # command_line=f"{dir_fire}/sim.sh",
            command_line="./sim.sh",
            # command_line="",
            # command_line=f"""-c 'cd {dir_fire} && ./sim.sh' """,
            container_settings=batchmodels.TaskContainerSettings(
                image_name=config._CONTAINER_BIN,
                container_run_options=" ".join(
                    [
                        "--rm",
                        # f"--entrypoint=\"/bin/bash -c 'cd {dir_fire} && ./sim.sh'\"",
                        # "--entrypoint /bin/bash",
                        "--entrypoint /bin/sh",
                        f"--workdir {dir_fire}",
                        # "--entrypoint ./sim.sh",
                        # f"--workdir /appl/tbd",
                        f"-v /mnt/batch/tasks/fsmounts/{RELATIVE_MOUNT_PATH}:/appl/data",
                    ]
                ),
                registry=batchmodels.ContainerRegistry(
                    user_name=config._REGISTRY_USER_NAME,
                    password=config._REGISTRY_PASSWORD,
                    registry_server=config._REGISTRY_SERVER,
                ),
            ),
            user_identity=batchmodels.UserIdentity(
                auto_user=batchmodels.AutoUserSpecification(
                    scope=batchmodels.AutoUserScope.pool,
                    elevation_level=batchmodels.ElevationLevel.admin,
                )
            ),
        )
    )
    batch_client.task.add_collection(job_id, tasks)
    return task_id


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
    return config._BATCH_ACCOUNT_NAME and config._BATCH_ACCOUNT_KEY


def get_batch_client():
    if not have_batch_config():
        return None
    return batch.BatchServiceClient(
        batchauth.SharedKeyCredentials(
            config._BATCH_ACCOUNT_NAME, config._BATCH_ACCOUNT_KEY
        ),
        batch_url=config._BATCH_ACCOUNT_URL,
    )


def run_pool(create_only=False):
    start_time = datetime.datetime.now().replace(microsecond=0)
    print("Sample start: {}".format(start_time))
    print()
    batch_client = get_batch_client()
    # try:
    pool_id = create_container_pool(batch_client)
    if not create_only:
        job_id = add_job(batch_client, pool_id=pool_id)
        add_monolithic_task(batch_client, job_id)
        wait_for_tasks_to_complete(batch_client, job_id)
    # except batchmodels.BatchErrorException as err:
    #     print_batch_exception(err)
    #     raise
    end_time = datetime.datetime.now().replace(microsecond=0)
    print()
    print("Sample end: {}".format(end_time))
    print("Elapsed time: {}".format(end_time - start_time))
    print()
    # batch_client.job.delete(job_id)


if __name__ == "__main__":
    run_pool(True)
