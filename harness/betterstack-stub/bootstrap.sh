#!/bin/sh
# docker/bootstrap/bootstrap.sh for `better-stack-logs` (stub variant from sdk-kit/harness/betterstack-stub).
# Checks both stub hosts answer like Better Stack, then hands the source + SQL API credentials to the tests.
set -eu
# shellcheck source=../../template/common/docker/bootstrap/lib.sh
. /scripts/lib.sh

: "${INGEST_URL:?}" "${QUERY_URL:?}" "${SOURCE_TOKEN:?}" "${SOURCE_TABLE:?}" "${QUERY_USER:?}" "${QUERY_PASSWORD:?}"

bootstrap_wait_http -q -t 60 "$INGEST_URL/__stub/health"
bootstrap_wait_http -q -t 60 "$QUERY_URL/ping"
# the query host must demand credentials
bootstrap_wait_http -q -t 5 -s 401 "$QUERY_URL/?query=SELECT%201"

bootstrap_begin
bootstrap_set BETTERSTACK_SOURCE_TOKEN "$SOURCE_TOKEN"
bootstrap_set BETTERSTACK_INGESTING_HOST "${INGEST_URL#http://}"
bootstrap_set BETTERSTACK_INGESTING_URL "$INGEST_URL"
bootstrap_set BETTERSTACK_QUERY_HOST "${QUERY_URL#http://}"
bootstrap_set BETTERSTACK_QUERY_URL "$QUERY_URL"
bootstrap_set BETTERSTACK_QUERY_USERNAME "$QUERY_USER"
bootstrap_set BETTERSTACK_QUERY_PASSWORD "$QUERY_PASSWORD"
bootstrap_set BETTERSTACK_SOURCE_TABLE "$SOURCE_TABLE"
bootstrap_commit
