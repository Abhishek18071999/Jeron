#!/bin/sh
# Builds a PDF from one part of the architecture documents:
#   sh docs/architecture/tools/build.sh docs/architecture/part-1-understanding-jeron.md out.pdf
# Needs pandoc, Node with Playwright and Chromium, and network access to cdn.jsdelivr.net
# (Mermaid draws the diagrams in the browser).
set -e
here=$(cd "$(dirname "$0")" && pwd)
src=$1; out=$2; html="${out%.pdf}.html"
pandoc "$src" --standalone --from gfm+yaml_metadata_block --to html5 \
  --metadata-file=/dev/null --css "$here/style.css" --embed-resources \
  --metadata pagetitle="Jeron architecture" -o "$html"
node "$here/print.js" "$html" "$out"
