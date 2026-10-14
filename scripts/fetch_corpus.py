#!/usr/bin/env python3
"""Download the public-domain development corpus into corpus/ (gitignored).

Usage: uv run scripts/fetch_corpus.py [monte-cristo ...]
Same as: uv run tome corpus fetch [KEY ...]
"""

import sys

from tome.corpus import CATALOG, fetch

keys = sys.argv[1:] or list(CATALOG)
for key in keys:
    print(f"{key}: {fetch(key)}")
