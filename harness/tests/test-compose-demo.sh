#!/bin/sh
# shellcheck disable=SC2015 # pass() never fails, so "a && pass || fail" is safe
# test-compose-demo.sh — end-to-end test of the Docker harness with the demo service.
#
# Renders the docker/ folder of a `demo` repository, replaces the Python test image by a tiny curl
# probe and runs it through compose-run.sh. Proves:
#   1. bootstrap env sharing: /bootstrap/env written by bootstrap, read-only in the test container
#   2. health gating: the probe starts only after the service is healthy and bootstrap exited 0;
#      an unhealthy service or a failing bootstrap keeps the probe from starting
#   3. demo server contract incl. /__fault controls against a real container
#   4. cleanup: no container, volume or network of the project survives, also after failures
#
# Run it under a Docker lock (it uses Docker; it never publishes host ports):
#   flock ~/grow/.artifcats/locks/sdk-docker-1.lock harness/tests/test-compose-demo.sh
set -eu

kit=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/sdk-harness-test.XXXXXX")
repo="$work/demo"
runner="$repo/docker/harness/compose-run.sh"
failures=0
projects=""

log() { printf '\n=== %s\n' "$*" >&2; }
pass() { printf 'PASS %s\n' "$*" >&2; }
fail() {
	printf 'FAIL %s\n' "$*" >&2
	failures=$((failures + 1))
}

finish() {
	for p in $projects; do
		docker compose -p "$p" down -v --remove-orphans >/dev/null 2>&1 || true
	done
	rm -rf "$work"
}
trap finish EXIT

new_project() {
	p="sdk-harness-test-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
	projects="$projects $p"
	printf '%s' "$p"
}

assert_clean() { # PROJECT LABEL
	left=$(docker ps -aq --filter "label=com.docker.compose.project=$1")
	vols=$(docker volume ls -q --filter "label=com.docker.compose.project=$1")
	nets=$(docker network ls -q --filter "label=com.docker.compose.project=$1")
	imgs=$(docker images -q "grow-sdk-demo-test-python:$1")
	if [ -z "$left$vols$nets$imgs" ]; then
		pass "$2: project $1 fully removed (incl. test image)"
	else
		fail "$2: leftovers for $1: containers=[$left] volumes=[$vols] networks=[$nets] images=[$imgs]"
	fi
}

# --- render the demo repository + a curl probe as the "python" suite -------------------------
"$kit/harness/tests/render-demo-repo.sh" "$repo"
mkdir -p "$repo/probe"
cat >"$repo/docker/Dockerfile.python" <<'EOF'
FROM curlimages/curl:8.17.0
COPY --chmod=0555 probe/probe.sh /probe.sh
ENTRYPOINT ["/bin/sh", "/probe.sh"]
EOF
cat >"$repo/probe/probe.sh" <<'EOF'
#!/bin/sh
set -eu
echo "probe: start"
fail() { echo "probe: FAIL $*"; exit 1; }
status() { curl -s -o /dev/null -w '%{http_code}' "$@"; }

# 1. bootstrap env sharing
[ -f /bootstrap/env ] || fail "/bootstrap/env missing"
token=$(sed -n 's/^GROW_DEMO_TOKEN=//p' /bootstrap/env)
[ -n "$token" ] || fail "GROW_DEMO_TOKEN missing in /bootstrap/env"
if touch /bootstrap/write-test 2>/dev/null; then fail "/bootstrap is writable"; fi
[ "$GROW_BOOTSTRAP_ENV" = /bootstrap/env ] || fail "GROW_BOOTSTRAP_ENV"
[ -n "$GROW_TEST_RUN_ID" ] && [ "$GROW_TEST_RUN_ID" != local ] || fail "GROW_TEST_RUN_ID not set by compose-run"
[ "$GROW_DEMO_URL" = http://service:8080 ] || fail "GROW_DEMO_URL=$GROW_DEMO_URL"
echo "probe: bootstrap env ok"

# 2. health gating: the health check and bootstrap already called /health before we started
health_calls=$(curl -fsS "$GROW_DEMO_URL/__stats" | sed -n 's/.*"\/health":\([0-9]*\).*/\1/p')
[ "${health_calls:-0}" -ge 2 ] || fail "expected >= 2 /health calls before the probe, got ${health_calls:-0}"
echo "probe: gating ok ($health_calls /health calls before start)"

# 3. demo contract
[ "$(curl -fsS "$GROW_DEMO_URL/health")" = '{"status":"ok"}' ] || fail "/health body"
[ "$(curl -fsS "$GROW_DEMO_URL/version")" = '{"version":"1.0.0"}' ] || fail "/version body"
[ "$(curl -fsS -H "Authorization: Bearer $token" "$GROW_DEMO_URL/v1/ping")" = '{"pong":true}' ] || fail "/v1/ping with token"
[ "$(status "$GROW_DEMO_URL/v1/ping")" = 401 ] || fail "/v1/ping without token must be 401"
[ "$(status -H 'Authorization: Bearer nope' "$GROW_DEMO_URL/v1/ping")" = 401 ] || fail "/v1/ping bad token must be 401"
[ "$(status http://demo:8080/health)" = 200 ] || fail "network alias demo"
curl -fsS -X POST -H 'Content-Type: application/json' \
  -d '[{"status":503,"count":2,"path":"/version"},{"status":429,"retryAfter":"1","path":"/version"}]' \
  "$GROW_DEMO_URL/__fault" >/dev/null
[ "$(status "$GROW_DEMO_URL/version")" = 503 ] || fail "fault 1"
[ "$(status "$GROW_DEMO_URL/version")" = 503 ] || fail "fault 2"
curl -s -D /tmp/h -o /dev/null "$GROW_DEMO_URL/version"
grep -qi '^retry-after: 1' /tmp/h || fail "Retry-After header"
[ "$(status "$GROW_DEMO_URL/version")" = 200 ] || fail "after faults"
echo "probe: demo contract ok"

if [ "${1:-}" = sleep ]; then
	echo "probe: sleeping"
	sleep 300
fi
if [ "${1:-}" = fail ]; then
	echo "probe: failing on purpose"
	exit 3
fi
echo "probe: all ok"
EOF

docker image inspect curlimages/curl:8.17.0 >/dev/null 2>&1 || docker pull -q curlimages/curl:8.17.0 >/dev/null

# --- 1. success path ------------------------------------------------------------------------------
log "success path"
p=$(new_project)
out="$work/run1.log"
rc=0
"$runner" -P "$p" -t 600 python >"$out" 2>&1 || rc=$?
if [ "$rc" -eq 0 ] && grep -q 'probe: all ok' "$out"; then
	pass "suite passed through compose-run.sh"
else
	fail "success path rc=$rc"
	cat "$out" >&2
fi
grep -q 'probe: gating ok' "$out" && pass "health gating observed" || fail "gating line missing"
grep -q 'bootstrap: set GROW_DEMO_TOKEN' "$out" && fail "bootstrap log leaked into a passing run" || true
if grep -q 'demo-local-token' "$out"; then fail "token value printed"; else pass "token value never printed"; fi
assert_clean "$p" "success path"

# --- 2. failing test: logs printed, exit status kept, cleanup ----------------------------------------
log "failing test container"
p=$(new_project)
out="$work/run2.log"
rc=0
"$runner" -P "$p" -n python -- fail >"$out" 2>&1 || rc=$?
[ "$rc" -eq 3 ] && pass "exit status 3 propagated" || {
	fail "expected exit 3, got $rc"
	cat "$out" >&2
}
grep -q 'demo: listening' "$out" && pass "service logs printed on failure" || fail "service logs missing"
grep -q 'bootstrap: wrote /bootstrap/env' "$out" && pass "bootstrap logs printed on failure" || fail "bootstrap logs missing"
assert_clean "$p" "failing test"

# --- 3. unhealthy service: probe never starts --------------------------------------------------------
log "unhealthy service blocks the suite"
cat >"$work/unhealthy.yml" <<'EOF'
services:
  service:
    healthcheck:
      test: ["CMD", "false"]
      interval: 1s
      timeout: 1s
      retries: 2
      start_period: 0s
      start_interval: 1s
EOF
p=$(new_project)
out="$work/run3.log"
rc=0
"$runner" -P "$p" -n -f "$repo/docker/compose.yml" -f "$work/unhealthy.yml" python >"$out" 2>&1 || rc=$?
if [ "$rc" -ne 0 ] && ! grep -q 'probe: start' "$out"; then
	pass "unhealthy service: suite did not start (rc=$rc)"
else
	fail "unhealthy service: rc=$rc"
	cat "$out" >&2
fi
assert_clean "$p" "unhealthy service"

# --- 4. failing bootstrap: probe never starts, bootstrap log shown ------------------------------------
log "failing bootstrap blocks the suite"
cat >"$work/badboot.yml" <<'EOF'
services:
  bootstrap:
    environment:
      DEMO_TOKEN: wrong-token
EOF
p=$(new_project)
out="$work/run4.log"
rc=0
"$runner" -P "$p" -n -f "$repo/docker/compose.yml" -f "$work/badboot.yml" python >"$out" 2>&1 || rc=$?
if [ "$rc" -ne 0 ] && ! grep -q 'probe: start' "$out" && grep -q 'rejected DEMO_TOKEN' "$out"; then
	pass "failing bootstrap: suite did not start, reason logged (rc=$rc)"
else
	fail "failing bootstrap: rc=$rc"
	cat "$out" >&2
fi
assert_clean "$p" "failing bootstrap"

# --- 5. interrupted run still cleans up ----------------------------------------------------------------
log "SIGTERM during the run"
p=$(new_project)
out="$work/run5.log"
"$runner" -P "$p" -n python -- sleep >"$out" 2>&1 &
pid=$!
i=0
while [ $i -lt 90 ] && ! grep -q 'probe: sleeping' "$out"; do
	sleep 1
	i=$((i + 1))
done
grep -q 'probe: sleeping' "$out" || fail "probe never reached its sleep"
started=$(date +%s)
kill -TERM "$pid" 2>/dev/null || true
rc=0
wait "$pid" || rc=$?
took=$(($(date +%s) - started))
[ "$rc" -eq 143 ] && pass "terminated run exits 143" || fail "terminated run exited $rc"
[ "$took" -lt 60 ] && pass "terminated run stopped in ${took}s" || fail "terminated run took ${took}s"
assert_clean "$p" "terminated run"

if [ "$failures" -eq 0 ]; then
	printf '\nall harness checks passed\n' >&2
else
	printf '\n%d harness check(s) failed\n' "$failures" >&2
	exit 1
fi
