import datetime

_POOL_VM_SIZE = "STANDARD_F72S_V2"
# _POOL_VM_SIZE = "STANDARD_HB120RS_V2"
_POOL_ID_BOTH = "pool_firestarr_both"
_POOL_ID_PY = "pool_firestarr_py"
_POOL_ID_BIN = "pool_firestarr_bin"
_MIN_NODES = 1
_MAX_NODES = 100
_AUTO_SCALE_FORMULA = "\n".join(
    [
        "$samples = $ActiveTasks.GetSamplePercent(TimeInterval_Minute);",
        "$tasks = $samples < 1 ? 0 : $ActiveTasks.GetSample(1);",
        f"$TargetDedicatedNodes = max({_MIN_NODES}, min({_MAX_NODES}, $tasks));",
        "$NodeDeallocationOption = taskcompletion;",
    ]
)
_AUTO_SCALE_EVALUATION_INTERVAL = datetime.timedelta(minutes=5)
_BATCH_ACCOUNT_NAME = ""
_BATCH_ACCOUNT_KEY = ""
_BATCH_ACCOUNT_URL = f"https://{_BATCH_ACCOUNT_NAME}.canadacentral.batch.azure.com"
_STORAGE_ACCOUNT_NAME = ""
_STORAGE_CONTAINER = ""
_STORAGE_KEY = ""
_REGISTRY_USER_NAME = ""
_REGISTRY_PASSWORD = ""
_REGISTRY_SERVER = f"{_REGISTRY_USER_NAME}.azurecr.io"
_CONTAINER_PY = f"{_REGISTRY_SERVER}/firestarr/tbd_prod_stable:latest"
_CONTAINER_BIN = f"{_REGISTRY_SERVER}/firestarr/firestarr:latest"
