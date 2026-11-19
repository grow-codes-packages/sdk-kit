#!/bin/sh
# docker/bootstrap/bootstrap.sh for `datadog-logs` (fakeintake variant from sdk-kit/harness/fakeintake).
# Makes the logs route answer like the real Datadog Logs intake (202 + "{}") and hands the API key
# and the fakeintake query URL to the tests.
set -eu
# shellcheck source=../../template/common/docker/bootstrap/lib.sh
. /scripts/lib.sh

: "${FAKEINTAKE_URL:?}" "${DD_API_KEY:?}"

bootstrap_wait_http -q -t 60 "$FAKEINTAKE_URL/fakeintake/health"
# body is a Go []byte, i.e. base64 in JSON: "e30=" = "{}"
override='{"endpoint":"/api/v2/logs","method":"POST","status_code":202,"content_type":"application/json","body":"e30="}'
wget -q -O /dev/null --header "Content-Type: application/json" --post-data "$override" \
	"$FAKEINTAKE_URL/fakeintake/configure/override" || bootstrap_fail "could not configure the /api/v2/logs override"

bootstrap_begin
bootstrap_set DD_API_KEY "$DD_API_KEY"
bootstrap_set DD_SITE "datadoghq.com"
bootstrap_set FAKEINTAKE_URL "$FAKEINTAKE_URL"
bootstrap_commit
