# Build the archive family for one build, named `triple` or `triple:option`.
build target tag:
  uv run ./build.py --target {{target}} --tag {{tag}}

# Build twice and prove the archives are byte identical.
build-reproducible target tag:
  #!/usr/bin/env bash
  set -euxo pipefail
  rm -rf dist dist-second-build
  uv run ./build.py --target {{target}} --tag {{tag}} --output-dir dist
  uv run ./build.py --target {{target}} --tag {{tag}} --output-dir dist-second-build
  diff dist/SHA256SUMS dist-second-build/SHA256SUMS
  echo "byte identical across runs"

# Generate the uv download-metadata catalog from a build receipt.
catalog target tag:
  uv run ./generate-catalog.py --target {{target}} --tag {{tag}}

# Confirm a committed device receipt covers the artifacts just built.
check-qualification target tag:
  uv run ./check-qualification.py --target {{target}} --tag {{tag}}

# Render the release notes for a tag from its build receipts.
release-notes tag:
  uv run ./release-notes.py --tag {{tag}}

# Lint, format check, and typecheck.
check:
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy pythonbuild build.py generate-catalog.py

# Apply every automatic fix.
fmt:
  uv run ruff check --fix .
  uv run ruff format .

# Print PYTHON.json from a full archive.
cat-python-json archive:
  zstd -dc {{archive}} | tar -x --to-stdout python/PYTHON.json

# Compare two archives with diffoscope.
diff a b:
  diffoscope \
    --html build/diff.html \
    --exclude 'python/build/**' \
    --max-diff-block-lines 100000 \
    --max-page-diff-block-lines 100000 \
    {{a}} {{b}}
