#!/bin/sh
# shellcheck disable=SC2015 # pass() never fails, so "a && pass || fail" is safe
# test-wait-for.sh — tests for wait-for-http.sh (curl and wget clients) and wait-for-tcp.sh
# (nc, bash, python3 and curl probes) against a local Python server. No Docker needed.
set -eu

kit=$(cd "$(dirname "$0")/../.." && pwd)
http="$kit/template/common/docker/harness/wait-for-http.sh"
tcp="$kit/template/common/docker/harness/wait-for-tcp.sh"
work=$(mktemp -d "${TMPDIR:-/tmp}/sdk-wait-test.XXXXXX")
failures=0
server_pid=""

pass() { printf 'PASS %s\n' "$*" >&2; }
fail() {
	printf 'FAIL %s\n' "$*" >&2
	failures=$((failures + 1))
}
finish() {
	[ -z "$server_pid" ] || kill "$server_pid" 2>/dev/null || true
	rm -rf "$work"
}
trap finish EXIT

# Server: /status/NNN answers NNN; /auth answers 200 only with "X-Token: abc"; /late answers
# 503 for the first two calls, then 200.
cat >"$work/server.py" <<'PY'
import http.server, sys
calls = {"late": 0}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/status/"):
            code = int(self.path.rsplit("/", 1)[1])
        elif self.path == "/auth":
            code = 200 if self.headers.get("X-Token") == "abc" else 401
        elif self.path == "/late":
            calls["late"] += 1
            code = 200 if calls["late"] > 2 else 503
        else:
            code = 404
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()
srv = http.server.HTTPServer(("127.0.0.1", 0), H)
srv.handle_error = lambda *args: None  # TCP probes (nc, curl telnet://) are not HTTP clients
print(srv.server_address[1], flush=True)
srv.serve_forever()
PY
python3 -I "$work/server.py" >"$work/port" &
server_pid=$!
i=0
while [ ! -s "$work/port" ] && [ $i -lt 50 ]; do
	sleep 0.1
	i=$((i + 1))
done
port=$(cat "$work/port")
base="http://127.0.0.1:$port"
closed=$(python3 -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')

# A PATH without curl, so wait-for-http.sh falls back to wget.
mkdir -p "$work/nocurl" "$work/onlycurl" "$work/bashonly" "$work/pyonly" "$work/none"
for tool in sh sed tail date sleep mktemp rm cat printf wget; do
	p=$(command -v "$tool" 2>/dev/null) && ln -sf "$p" "$work/nocurl/$tool"
done
for tool in sh date sleep curl; do ln -sf "$(command -v "$tool")" "$work/onlycurl/$tool"; done
for tool in sh date sleep bash; do ln -sf "$(command -v "$tool")" "$work/bashonly/$tool"; done
for tool in sh date sleep python3; do ln -sf "$(command -v "$tool")" "$work/pyonly/$tool"; done
for tool in sh date sleep; do ln -sf "$(command -v "$tool")" "$work/none/$tool"; done

expect_rc() { # WANT LABEL CMD...
	want=$1
	label=$2
	shift 2
	rc=0
	"$@" >/dev/null 2>&1 || rc=$?
	[ "$rc" -eq "$want" ] && pass "$label (rc=$rc)" || fail "$label: want rc=$want, got $rc"
}

for client in curl wget; do
	if [ "$client" = curl ]; then run() { sh "$http" "$@"; }; else run() { PATH="$work/nocurl" sh "$http" "$@"; }; fi
	expect_rc 0 "$client: 200 ready" run -q -t 5 "$base/status/200"
	expect_rc 0 "$client: expected 404" run -q -t 5 -s 404 "$base/status/404"
	expect_rc 0 "$client: status list" run -q -t 5 -s 200,204 "$base/status/204"
	expect_rc 0 "$client: 2xx class" run -q -t 5 -s 2xx "$base/status/202"
	expect_rc 1 "$client: wrong status times out" run -q -t 1 "$base/status/500"
	expect_rc 0 "$client: header sent" run -q -t 5 -H "X-Token: abc" "$base/auth"
	expect_rc 0 "$client: 401 without header" run -q -t 5 -s 401 "$base/auth"
	expect_rc 1 "$client: closed port times out" run -q -t 1 "http://127.0.0.1:$closed/"
done
expect_rc 0 "retries until ready" sh "$http" -t 10 "$base/late"
expect_rc 2 "http: missing url" sh "$http"
expect_rc 2 "http: bad scheme" sh "$http" "ftp://x"
expect_rc 2 "http: bad timeout" sh "$http" -t x "$base/"
expect_rc 2 "http: unknown flag" sh "$http" -z "$base/"
expect_rc 2 "http: no client" env PATH="$work/none" sh "$http" "$base/"
out=$(sh "$http" -t 1 -H "Authorization: Bearer topsecret" "$base/status/500" 2>&1 || true)
case $out in *topsecret*) fail "header value printed" ;; *) pass "header value not printed" ;; esac
case $out in *"last status 500"*) pass "timeout message names the last status" ;; *) fail "timeout message: $out" ;; esac

expect_rc 0 "tcp: open port (default client)" sh "$tcp" -q -t 5 "127.0.0.1:$port"
expect_rc 1 "tcp: closed port" sh "$tcp" -q -t 1 "127.0.0.1:$closed"
for dir in onlycurl bashonly pyonly; do
	expect_rc 0 "tcp/$dir: open port" env PATH="$work/$dir" sh "$tcp" -q -t 5 "127.0.0.1:$port"
	expect_rc 1 "tcp/$dir: closed port" env PATH="$work/$dir" sh "$tcp" -q -t 1 "127.0.0.1:$closed"
done
expect_rc 0 "tcp: [ipv6-style] brackets" sh "$tcp" -q -t 5 "[127.0.0.1]:$port"
expect_rc 2 "tcp: no client" env PATH="$work/none" sh "$tcp" "127.0.0.1:$port"
expect_rc 2 "tcp: missing port" sh "$tcp" "127.0.0.1"
expect_rc 2 "tcp: bad port" sh "$tcp" "127.0.0.1:x"
expect_rc 2 "tcp: bad timeout" sh "$tcp" -t x "127.0.0.1:1"
expect_rc 2 "tcp: unknown flag" sh "$tcp" -z "127.0.0.1:1"

if [ "$failures" -eq 0 ]; then
	printf 'all wait-for checks passed\n' >&2
else
	printf '%d wait-for check(s) failed\n' "$failures" >&2
	exit 1
fi
