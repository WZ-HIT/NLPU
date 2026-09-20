# Contracts

No public interface changes are expected. The workflow contract is:

- `TOXENV=vcs-deps` remains the VCS dependency test entry point.
- Existing pytest warning policy remains in force unless a narrowly scoped exception is justified.
- The workflow continues installing development revisions rather than release pins.
