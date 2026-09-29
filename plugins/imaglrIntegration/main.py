# SPDX-License-Identifier: AGPL-3.0-only
"""Entry point Stash runs for every plugin operation and task (raw interface).

Stash writes one JSON request to stdin and parses all of stdout as {"output": ..., "error": ...},
so nothing else may ever be printed to stdout. Logging goes to stderr (see imaglr_integration.log).
"""

import json
import sys

from imaglr_integration import app


def main():
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    output, error = app.handle(request)
    sys.stdout.write(json.dumps({"output": output, "error": error}))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
