#!/bin/sh
# shellcheck disable=SC2015 # pass() never fails, so "a && pass || fail" is safe
# test-compose-emulators.sh — the emulator compose variants (moto, fakeintake, betterstack-stub) as
# drop-in docker/compose.service.yml files: each runs through compose-run.sh with a small probe as
# the "python" suite that uses /bootstrap/env the way an SDK integration test would.
#
#   flock ~/grow/.artifcats/locks/sdk-docker-1.lock harness/tests/test-compose-emulators.sh [moto|fakeintake|betterstack]...
set -eu

kit=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d "${TMPDIR:-/tmp}/sdk-emulator-test.XXXXXX")
failures=0
projects=""
variants=${*:-moto fakeintake betterstack}

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

run_variant() { # NAME KEY PROBE_BASE_IMAGE
	name=$1
	key=$2
	base=$3
	repo="$work/$name"
	python3 -I "$kit/harness/tests/render_repo.py" "$repo" "$key"
	mkdir -p "$repo/probe"
	cp "$work/probe-$name.py" "$repo/probe/probe.py"
	cp "$kit/harness/fakeintake/fakeintake.py" "$repo/probe/fakeintake.py"
	cat >"$repo/docker/Dockerfile.python" <<EOF
FROM $base
COPY probe/ /probe/
ENTRYPOINT ["python", "/probe/probe.py"]
EOF
	p="sdk-emulator-test-$name-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
	projects="$projects $p"
	out="$work/$name.log"
	rc=0
	"$repo/docker/harness/compose-run.sh" -P "$p" -t 900 python >"$out" 2>&1 || rc=$?
	if [ "$rc" -eq 0 ] && grep -q "probe: all ok" "$out"; then
		pass "$name: probe passed"
	else
		fail "$name: rc=$rc"
		cat "$out" >&2
	fi
	left=$(docker ps -aq --filter "label=com.docker.compose.project=$p")$(docker volume ls -q --filter "label=com.docker.compose.project=$p")
	[ -z "$left" ] && pass "$name: cleaned up" || fail "$name: leftovers $left"
}

# Shared helper for the probes: read /bootstrap/env like the SDK tests do.
cat >"$work/envfile.py" <<'EOF'
import os

def load_bootstrap_env(path="/bootstrap/env"):
    values = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            values[key] = value
    os.environ.update(values)
    return values
EOF

cat "$work/envfile.py" - >"$work/probe-moto.py" <<'EOF'
import sys, time
import boto3

env = load_bootstrap_env()
assert env["AWS_ENDPOINT_URL"] == "http://service:5000", env.get("AWS_ENDPOINT_URL")
assert os.environ["GROW_AWS_SECRETS_MANAGER_URL"] == "http://service:5000"
# boto3 picks up AWS_ENDPOINT_URL_* and the credential chain from the environment by itself
sm = boto3.client("secretsmanager")
assert sm.get_secret_value(SecretId="grow-conformance/seed")["SecretString"] == "seed-value"
sm.create_secret(Name="probe/new", SecretString="v1")
assert sm.get_secret_value(SecretId="probe/new")["SecretString"] == "v1"
logs = boto3.client("logs")
group, stream = env["CLOUDWATCH_LOG_GROUP"], env["CLOUDWATCH_LOG_STREAM"]
logs.put_log_events(logGroupName=group, logStreamName=stream,
                    logEvents=[{"timestamp": int(time.time() * 1000), "message": "probe hello"}])
events = logs.get_log_events(logGroupName=group, logStreamName=stream)["events"]
assert [e["message"] for e in events] == ["probe hello"], events
print("probe: all ok")
EOF

cat "$work/envfile.py" - >"$work/probe-fakeintake.py" <<'EOF'
import gzip, json, sys, urllib.request
sys.path.insert(0, "/probe")
import fakeintake

env = load_bootstrap_env()
url = os.environ["GROW_DATADOG_LOGS_URL"]
assert url == "http://service:80", url
run = os.environ["GROW_TEST_RUN_ID"]
body = gzip.compress(json.dumps([{"message": f"probe {run}", "service": "probe", "ddsource": "sdk",
                                  "ddtags": "env:test", "attr": {"run": run}}]).encode())
req = urllib.request.Request(f"{url}/api/v2/logs", data=body, method="POST", headers={
    "DD-API-KEY": env["DD_API_KEY"], "Content-Type": "application/json", "Content-Encoding": "gzip"})
with urllib.request.urlopen(req, timeout=10) as resp:
    assert resp.status == 202, resp.status  # bootstrap override mimics the real intake
    assert json.loads(resp.read()) == {}
assert fakeintake.wait(env["FAKEINTAKE_URL"], "/api/v2/logs", contains=run, timeout=20) == 1
record = fakeintake.logs(env["FAKEINTAKE_URL"], contains=run)[0]
assert record["attr"] == {"run": run}
parsed = json.loads(urllib.request.urlopen(f"{url}/fakeintake/payloads?endpoint=/api/v2/logs&format=json").read())
assert parsed["payloads"][0]["data"][0]["message"] == f"probe {run}"
assert fakeintake.last_api_key(env["FAKEINTAKE_URL"], reveal=True) == env["DD_API_KEY"]
# any other intake path is accepted too (APM traces from a datadog/agent land on /api/v0.2/traces)
req = urllib.request.Request(f"{url}/api/v0.2/traces", data=gzip.compress(b"\x00"), method="POST",
                             headers={"Content-Encoding": "gzip", "Content-Type": "application/x-protobuf"})
assert urllib.request.urlopen(req, timeout=10).status == 200
assert fakeintake.routes(env["FAKEINTAKE_URL"])["/api/v0.2/traces"] == 1
print("probe: all ok")
EOF

cat "$work/envfile.py" - >"$work/probe-betterstack.py" <<'EOF'
import base64, gzip, json, urllib.error, urllib.parse, urllib.request

env = load_bootstrap_env()
ingest, query_url = env["BETTERSTACK_INGESTING_URL"], env["BETTERSTACK_QUERY_URL"]
assert os.environ["GROW_BETTER_STACK_LOGS_URL"] == ingest == "http://" + env["BETTERSTACK_INGESTING_HOST"]
run = os.environ["GROW_TEST_RUN_ID"]

def post(body, headers):
    req = urllib.request.Request(ingest + "/", data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()

auth = {"Authorization": "Bearer " + env["BETTERSTACK_SOURCE_TOKEN"]}
status, body = post(gzip.compress(json.dumps([{"message": f"probe {run}", "dt": 1700000000123}]).encode()),
                    {**auth, "Content-Type": "application/json", "Content-Encoding": "gzip"})
assert (status, body) == (202, b""), (status, body)
assert post(b'{"message":"x"}', {"Authorization": "Bearer nope", "Content-Type": "application/json"}) == (403, b"Unauthorized")
assert post(b"{bad", {**auth, "Content-Type": "application/json"}) == (406, b"Couldn't parse JSON content.")
sql = (f"SELECT dt, raw FROM remote({env['BETTERSTACK_SOURCE_TABLE']}_logs) WHERE raw LIKE '%{run}%' "
       "ORDER BY dt DESC LIMIT 100 FORMAT JSONEachRow")
creds = base64.b64encode(f"{env['BETTERSTACK_QUERY_USERNAME']}:{env['BETTERSTACK_QUERY_PASSWORD']}".encode()).decode()
req = urllib.request.Request(query_url + "/?output_format_pretty_row_numbers=0", data=sql.encode(), method="POST",
                             headers={"Authorization": "Basic " + creds, "Content-type": "plain/text"})
rows = [json.loads(line) for line in urllib.request.urlopen(req, timeout=10).read().decode().splitlines()]
assert len(rows) == 1 and json.loads(rows[0]["raw"])["message"] == f"probe {run}", rows
assert rows[0]["dt"] == "2023-11-14 22:13:20.123000", rows[0]["dt"]
# OTLP/HTTP JSON logs on the same host + token, then a parameter-bound query finds them
otlp_doc = {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"timeUnixNano": "1700000000123456789",
            "body": {"stringValue": f"otlp {run}"}, "severityText": "INFO"}]}]}]}
req = urllib.request.Request(ingest + "/v1/logs", data=json.dumps(otlp_doc).encode(), method="POST",
                             headers={**auth, "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=10) as resp:
    assert resp.status == 200 and json.loads(resp.read()) == {}
params = urllib.parse.urlencode({"param_needle": f"otlp {run}", "param_t": env["BETTERSTACK_SOURCE_TABLE"] + "_logs"})
req = urllib.request.Request(query_url + "/?" + params, method="POST",
                             data=b"SELECT dt FROM remote({t:Identifier}) WHERE position(raw, {needle:String}) > 0 FORMAT JSONEachRow",
                             headers={"Authorization": "Basic " + creds})
rows = [json.loads(line) for line in urllib.request.urlopen(req, timeout=10).read().decode().splitlines()]
assert rows == [{"dt": "2023-11-14 22:13:20.123456"}], rows
print("probe: all ok")
EOF

for v in $variants; do
	case $v in
	moto) run_variant moto aws-secrets-manager motoserver/moto:5.2.5 ;;
	fakeintake) run_variant fakeintake datadog-logs python:3.13.18-alpine3.24 ;;
	betterstack) run_variant betterstack better-stack-logs python:3.13.18-alpine3.24 ;;
	*) fail "unknown variant $v" ;;
	esac
done

if [ "$failures" -eq 0 ]; then
	printf 'all emulator checks passed\n' >&2
else
	printf '%d emulator check(s) failed\n' "$failures" >&2
	exit 1
fi
