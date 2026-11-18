# moto (AWS emulator)

`motoserver/moto` in server mode emulates the AWS APIs for `aws-secrets-manager` and
`aws-cloudwatch-logs` (<https://docs.getmoto.org/en/latest/docs/server_mode.html>, Apache-2.0).

Pinned image: `motoserver/moto:5.2.5@sha256:59a1965d845249b04def37a0e2565f9cc6c44543cb89b68e90f28f344b3b0d1a`
(published 2026-10-27, latest release on 2026-11-18). It contains Python 3.13, boto3, `curl` and `wget`.

Files for a generated repo: `compose.service.yml` → `docker/compose.service.yml`, `bootstrap.py` →
`docker/bootstrap/bootstrap.py`.

- `service` listens on 5000 (`GROW_<KEY>_URL=http://service:5000`); health check
  `GET /moto-api/data.json`. `POST /moto-api/reset` resets all state (useful between scenarios).
- `bootstrap` runs `bootstrap.py` in the same image (boto3 included): creates the secrets from
  `MOTO_SECRETS` (JSON object) and the log group/stream from `MOTO_LOG_GROUP`/`MOTO_LOG_STREAM`,
  then writes to `/bootstrap/env`: `AWS_ACCESS_KEY_ID=testing`, `AWS_SECRET_ACCESS_KEY=testing`,
  `AWS_REGION`, `AWS_DEFAULT_REGION`, `AWS_ENDPOINT_URL`, `AWS_ENDPOINT_URL_SECRETS_MANAGER`,
  `AWS_ENDPOINT_URL_CLOUDWATCH_LOGS` (AWS service-specific endpoint variables),
  `AWS_EC2_METADATA_DISABLED=true`, and `CLOUDWATCH_LOG_GROUP` / `CLOUDWATCH_LOG_STREAM`.
- Known moto behaviour: CloudWatch Logs drops events older than 14 days (use current timestamps);
  any credentials are accepted (auth failures cannot be tested against moto — unit tests only).
