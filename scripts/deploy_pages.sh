#!/usr/bin/env bash
# Publish site/ to the gh-pages branch (one fresh commit each time, so main never carries generated data).
# Usage: scripts/deploy_pages.sh            (run `make site` first, or use `make deploy`)
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f site/index.html ] || { echo "site/ is empty: run 'make site' first"; exit 1; }
remote=$(git remote get-url origin)
email=$(git config user.email)
name=$(git config user.name)
tmp=$(mktemp -d)
cp -R site/. "$tmp/"
cd "$tmp"
git init -q -b gh-pages
git -c user.email="$email" -c user.name="$name" add -A
git -c user.email="$email" -c user.name="$name" commit -q -m "Deploy site $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q -f "$remote" gh-pages
cd - >/dev/null
rm -rf "$tmp"
echo "Pushed site/ to gh-pages. Live in ~1 min at the repo's GitHub Pages URL."
