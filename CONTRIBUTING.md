# Contributing

Bug reports and pull requests are welcome. A few things to know:

- **Read `dev/README.md`** for the local test environment (Stash in Docker, synthetic media, a fake imaglr) and
  how to run the tests. CI runs them all, including an end-to-end send inside a real Stash container.
- **Stay Stash-native.** The UI reuses Stash's own components and CSS classes wherever they exist and never
  re-implements a Stash feature. Phone use is a first-class requirement, not a polish step.
- **Standard library only** in the Python backend (it runs inside Stash's Docker image and on bare-metal
  installs with whatever Python is available, 3.9 or newer).
- **imaglr calls are allowlisted** (five routes, see `imaglr/client.py`); adding one is a design conversation,
  not a code change.
- **Privacy gate.** The repository is published anonymously. Enable the git hooks once per clone
  (`git config core.hooksPath .githooks`) so nothing personal — addresses, local paths, e-mail addresses,
  keys — can be committed. CI runs the same scan.
- **AI assistance** is used in this project and disclosed in the README; whatever tools you use, you are
  responsible for the code you submit and its licence compliance (AGPL-3.0).
