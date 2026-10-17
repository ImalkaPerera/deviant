"""Allow `python -m deviant_scan`."""

import sys

from .mine import main

sys.exit(main())
