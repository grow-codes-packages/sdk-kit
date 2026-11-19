#!/bin/sh
# render-demo-repo.sh DEST — lay out the docker/ folder of a generated `demo` repository in DEST.
set -eu
[ $# -eq 1 ] || {
	echo "usage: $0 DEST" >&2
	exit 2
}
exec python3 -I "$(dirname "$0")/render_repo.py" "$1" demo
