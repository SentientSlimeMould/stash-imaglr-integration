# SPDX-License-Identifier: AGPL-3.0-only
# Make the plugin's Python package importable, as it is when Stash runs main.py from the plugin folder.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "imaglrIntegration"))
