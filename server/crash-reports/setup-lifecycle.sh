#!/bin/bash
# The crash report bucket's lifecycle rule: reports are deleted 90 days after upload, as the
# report page and kettlelinux.org/legal.html say (the worker also stops serving them by then).
# Run once, after `npx wrangler login` (docs/CRASH-REPORTS.md); `npx wrangler r2 bucket lifecycle
# list kettle-crash-reports` shows it.
set -euo pipefail
cd "$(dirname "$0")"
npx wrangler r2 bucket lifecycle add kettle-crash-reports delete-reports-90d reports/ --expire-days 90 --force
