#!/usr/bin/env sh
# Mirror theme/ (source of truth, used by sdk-kit's own docs) into the repo template, where it
# becomes docs/.overrides/ of every generated repo (custom_dir of template/common/mkdocs.yml).
#   .github/scripts/sync-theme.sh          copy theme/ → template/common/docs/.overrides/
#   .github/scripts/sync-theme.sh --check  exit 1 when the mirror differs (CI)
set -eu
here=$(CDPATH= cd -- "$(dirname -- "$0")/../../theme" && pwd -P)
dest="$here/../template/common/docs/.overrides"
files="main.html grow.css partials/copyright.html .icons/grow/logo.svg assets/favicon.svg"

if [ "${1:-}" = "--check" ]; then
  status=0
  for f in $files; do
    if ! cmp -s "$here/$f" "$dest/$f"; then
      echo "theme mirror out of date: template/common/docs/.overrides/$f (run .github/scripts/sync-theme.sh)"
      status=1
    fi
  done
  extra=$(cd "$dest" && find . -type f | sed 's#^\./##' | sort)
  for f in $extra; do
    case " $files " in *" $f "*) ;; *) echo "unexpected file in mirror: $f"; status=1 ;; esac
  done
  [ "$status" -eq 0 ] && echo "theme mirror up to date"
  exit "$status"
fi

for f in $files; do
  mkdir -p "$(dirname -- "$dest/$f")"
  cp "$here/$f" "$dest/$f"
done
echo "mirrored theme/ to template/common/docs/.overrides/"
