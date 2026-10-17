"""Run the Deviant scan from this folder: python mine.py --repo <project> --with-git --json

A thin launcher. The code lives in the deviant_scan package next to this file, so the Claude
Code skill stays self-contained, and the same package is what `pip install deviant-scan`
installs as the `deviant-scan` command.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from deviant_scan.mine import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
