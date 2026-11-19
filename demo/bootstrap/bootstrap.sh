#!/bin/sh
# Bootstrap for the `demo` SDK (copied from sdk-kit/demo/bootstrap by `sdk-kit new demo`).
# Proves the token works against the running demo server, then hands it to the tests.
set -eu
# shellcheck source=../../template/common/docker/bootstrap/lib.sh
. /scripts/lib.sh

: "${SERVICE_URL:?SERVICE_URL is not set}"
: "${DEMO_TOKEN:?DEMO_TOKEN is not set}"

bootstrap_wait_http -q -t 60 "$SERVICE_URL/health"
bootstrap_wait_http -q -t 10 -s 401 "$SERVICE_URL/v1/ping"
bootstrap_wait_http -q -t 10 -H "Authorization: Bearer $DEMO_TOKEN" "$SERVICE_URL/v1/ping" ||
	bootstrap_fail "the demo server rejected DEMO_TOKEN"

bootstrap_begin
bootstrap_set GROW_DEMO_TOKEN "$DEMO_TOKEN"
bootstrap_commit
