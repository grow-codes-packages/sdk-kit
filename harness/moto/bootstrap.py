"""docker/bootstrap/bootstrap.py for the AWS services: prepare moto and write /bootstrap/env.

Runs inside the motoserver/moto image (Python + boto3 are part of it). Environment:
  MOTO_URL         moto endpoint (default http://service:5000)
  AWS_REGION       region (default us-east-1)
  MOTO_SECRETS     JSON object {name: value} -> Secrets Manager secrets to create
  MOTO_LOG_GROUP   CloudWatch Logs group to create (optional)
  MOTO_LOG_STREAM  stream inside MOTO_LOG_GROUP (optional)
  BOOTSTRAP_ENV    output file (default /bootstrap/env)
Writes the standard AWS credential chain variables, AWS_ENDPOINT_URL plus the service-specific
AWS_ENDPOINT_URL_SECRETS_MANAGER / AWS_ENDPOINT_URL_CLOUDWATCH_LOGS, and CLOUDWATCH_LOG_GROUP /
CLOUDWATCH_LOG_STREAM when a group is configured. Never prints secret values.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

import boto3  # part of the moto image

# moto accepts any credentials; these are the values its documentation uses.
ACCESS_KEY = "testing"
SECRET_KEY = "testing"


def log(message: str) -> None:
    sys.stderr.write(f"bootstrap: {message}\n")


def wait_for(url: str, timeout_s: float = 60) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(f"{url}/moto-api/data.json", timeout=3):
                return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def write_env(path: str, values: dict[str, str]) -> None:
    lines = ["# written by docker/bootstrap/bootstrap.py"]
    for key, value in values.items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or "\n" in value:
            raise ValueError(f"invalid env entry {key}")
        lines.append(f"{key}={value}")
        log(f"set {key}")
    target = Path(path)
    tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.chmod(0o644)
    tmp.replace(target)
    log(f"wrote {path}")


def main() -> int:
    url = os.environ.get("MOTO_URL", "http://service:5000").rstrip("/")
    region = os.environ.get("AWS_REGION", "us-east-1")
    wait_for(url)
    session = boto3.session.Session(
        aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY, region_name=region
    )
    env = {
        "AWS_ACCESS_KEY_ID": ACCESS_KEY,
        "AWS_SECRET_ACCESS_KEY": SECRET_KEY,
        "AWS_REGION": region,
        "AWS_DEFAULT_REGION": region,
        "AWS_ENDPOINT_URL": url,
        "AWS_ENDPOINT_URL_SECRETS_MANAGER": url,
        "AWS_ENDPOINT_URL_CLOUDWATCH_LOGS": url,
        "AWS_EC2_METADATA_DISABLED": "true",
    }

    secrets = json.loads(os.environ.get("MOTO_SECRETS", "") or "{}")
    if secrets:
        client = session.client("secretsmanager", endpoint_url=url)
        for name, value in secrets.items():
            client.create_secret(Name=name, SecretString=str(value))
        listed = {s["Name"] for s in client.list_secrets()["SecretList"]}
        missing = set(secrets) - listed
        if missing:
            raise RuntimeError(f"secrets not visible after create: {sorted(missing)}")
        log(f"created {len(secrets)} secret(s)")

    group = os.environ.get("MOTO_LOG_GROUP", "")
    if group:
        client = session.client("logs", endpoint_url=url)
        client.create_log_group(logGroupName=group)
        env["CLOUDWATCH_LOG_GROUP"] = group
        stream = os.environ.get("MOTO_LOG_STREAM", "")
        if stream:
            client.create_log_stream(logGroupName=group, logStreamName=stream)
            env["CLOUDWATCH_LOG_STREAM"] = stream
        groups = client.describe_log_groups(logGroupNamePrefix=group)["logGroups"]
        if not any(g["logGroupName"] == group for g in groups):
            raise RuntimeError("log group not visible after create")
        log(f"created log group {group}" + (f" with stream {stream}" if stream else ""))

    write_env(os.environ.get("BOOTSTRAP_ENV", "/bootstrap/env"), env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
