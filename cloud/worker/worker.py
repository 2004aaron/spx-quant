"""The Temporal worker as a Lambda function (Serverless Worker, public preview).

A worker is the process that runs workflow and activity code for a task queue. Here nothing
runs between emails: Temporal Cloud invokes this function when a task is waiting, the function
connects, works until the queue is quiet or its time is nearly up, and exits.

`run_worker` comes from the Temporal Python SDK (temporalio.contrib.aws.lambda_worker). It reads
TEMPORAL_ADDRESS and TEMPORAL_NAMESPACE from the function's environment. The API key is not an
environment variable: it is read from SSM Parameter Store (SecureString) on a cold start.
Serverless Workers need Worker Versioning, so the function reports a deployment name and a
build id, and the same pair is registered in Temporal Cloud (docs/operations.md).
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from temporalio.common import WorkerDeploymentVersion
from temporalio.contrib.aws.lambda_worker import LambdaWorkerConfig, run_worker

from activities import list_users, send_digest
from workflows import DigestWorkflow

QUEUE = "stormglass"
DEPLOYMENT = "stormglass"
STOP = timedelta(seconds=30)   # a send in flight when the invocation ends gets this long to finish
_key: str | None = None


def api_key() -> str:
    global _key
    if _key is None:
        import boto3
        name = os.environ.get("TEMPORAL_KEY_PARAM", "/stormglass/temporal/api_key")
        _key = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]
    return _key


def configure(config: LambdaWorkerConfig, key=api_key) -> None:
    config.worker_config.update(task_queue=QUEUE, workflows=[DigestWorkflow], activities=[list_users, send_digest],
                                activity_executor=ThreadPoolExecutor(max_workers=2), graceful_shutdown_timeout=STOP)
    config.shutdown_deadline_buffer = STOP + timedelta(seconds=5)
    if not config.client_connect_config.get("api_key"):
        config.client_connect_config["api_key"] = key()


lambda_handler = run_worker(WorkerDeploymentVersion(deployment_name=DEPLOYMENT, build_id=os.environ.get("BUILD_ID", "dev")), configure)
