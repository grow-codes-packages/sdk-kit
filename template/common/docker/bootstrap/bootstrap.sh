#!/bin/sh
# One-shot bootstrap for the Docker integration suites (sdk-kit SPEC §8).
#
# OWNED BY THIS REPOSITORY: sdk-kit writes this skeleton once and never overwrites it.
# Runs in the `bootstrap` service of docker/compose.service.yml after `service` is healthy.
# Prepare __DISPLAY__ for the tests (init/unseal, users, tokens, streams, buckets ...) and write
# the credentials the tests need to /bootstrap/env with bootstrap_set. Exit non-zero on failure:
# the test containers then never start and compose-run.sh prints this job's log.
# Never print secret values.
set -eu
# shellcheck source=lib.sh
. /scripts/lib.sh

: "${SERVICE_URL:?SERVICE_URL is not set}"

bootstrap_begin

# --- service-specific steps (replace) ---------------------------------------------------------
# Example: wait for an extra endpoint, create a token through the API and hand it to the tests.
#   bootstrap_wait_http -t 120 "$SERVICE_URL/health"
#   token=$(wget -q -O - --header "Authorization: Bearer $ADMIN_TOKEN" --post-data '{}' \
#     "$SERVICE_URL/api/tokens" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')
#   [ -n "$token" ] || bootstrap_fail "could not create a token"
#   bootstrap_set GROW___KEY_UPPER___TOKEN "$token"
# -------------------------------------------------------------------------------------------------

bootstrap_commit
