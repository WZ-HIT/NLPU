# Pre-experiment Rollback Checkpoint

This document explains the rollback checkpoint created immediately before the
first formal SDD experiment for Scrapy PR 8073, sample `600152fbc76dd5ba`.

## Checkpoint identity

- Checkpoint ID: `pre-experiment-pr8073-20260912T050742Z`
- Task ID: `scrapy__scrapy__8073__test_only__600152fbc76dd5ba`
- Task base commit: `11079cb1c85b9e75a39a7269943c69d1a975d485`
- Parent benchmark commit at capture time: `a1f007b`
- Checkpoint size: approximately 326 MiB
- Location: `checkpoints/pre-experiment-pr8073-20260912T050742Z/`

## What the checkpoint protects

The checkpoint uses several layers because a Git commit alone cannot reproduce
the complete experiment state.

1. **Scrapy repositories** — the baseline and all three experiment repositories
   are archived with their `.git` directories. This preserves the exact HEAD,
   branch, one-commit history, removed remotes, initialized SDD files, and working
   tree state.
2. **Independent Agent HOME volumes** — the OpenSpec, Spec Kit, and cc-sdd Docker
   HOME volumes are archived separately. This preserves each tool installation,
   Codex state, Python environment, and private caches without merging them.
3. **Deployment configuration** — Compose files, the launcher, deployment lock,
   provider profile, model catalog, egress proxy, Seccomp policy, and AppArmor
   source are archived together.
4. **Offline images** — the pinned Agent and HAProxy Docker images are exported.
   Recovery therefore does not depend on a registry, network access, or an image
   remaining in Docker's local cache.
5. **Integrity metadata** — `checkpoint.json` records the expected identities and
   `payloads/SHA256SUMS` protects every archive against accidental corruption.

The capture flow was:

```text
verify no Agent run is active
            |
pause three Agent containers
            |
archive four repositories + three HOME volumes + deployment configuration
            |
unpause three Agent containers
            |
export fixed Docker images
            |
generate SHA-256 checksums
            |
extract into temporary directories and validate Git identities
```

The API key is not stored in any checkpoint file. Experiment logs are also not
included, so restoring an earlier environment does not erase later audit output.
Unrelated changes elsewhere in the parent `/home/wangzuohit/NLPU` worktree are
outside the rollback scope.

## Verify before an experiment

Run verification whenever the checkpoint is copied, before a formal experiment,
or immediately before restoring it:

```bash
cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/checkpoints/\
pre-experiment-pr8073-20260912T050742Z
./verify.sh
```

Expected final output:

```text
checkpoint_metadata=PASS id=pre-experiment-pr8073-20260912T050742Z
checkpoint_verification=PASS
```

The command is read-only. It verifies all nine payload archives and checks the
checkpoint schema, repository count, HOME-volume count, and secret-exclusion
declaration.

## Restore the pre-experiment state

Do not start a new Agent run while restoring. Set the key path only in the shell;
the key file must be outside the benchmark tree, owned by the current user, and
must not grant permissions to group or other users.

```bash
cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/checkpoints/\
pre-experiment-pr8073-20260912T050742Z

DEEPSEEK_API_KEY_FILE=/absolute/path/outside/the/benchmark/tree \
  ./restore.sh --yes
```

The `--yes` argument is mandatory. Without it, the script exits before changing
anything.

During recovery, the script performs these operations in order:

1. verifies every checkpoint checksum;
2. refuses to continue if the formal-run lock is held;
3. validates the external API-key file without copying or printing its content;
4. reloads the pinned Docker images if either image is missing;
5. creates `restore-backups/<UTC timestamp>/` containing the current state;
6. restores the known-good deployment configuration before invoking Compose;
7. stops the six deployment containers while retaining the named HOME volumes;
8. replaces the four repositories and restores all three HOME volumes;
9. starts the same isolated deployment and runs the launcher's runtime checks.

The restore-time backup is deliberately created before replacement. If recovery
is interrupted, the displaced repositories and the current configuration remain
available there, together with compressed copies of the three previous HOME
volumes.

## Safety properties

- The four repository archives include `.git`; restore does not rely on a remote.
- Each SDD repository and HOME volume has its own archive and restore target.
- Restore does not combine or share `.venv`, `.tox`, cache, session, or HOME data.
- The secret is supplied only when containers are restarted and is never archived.
- Large payloads and restore backups are ignored by Git; human-readable metadata
  and scripts remain eligible for version control.
- The fixed image archive was tested with `docker image load`.
- All repository archives were test-extracted and confirmed to retain their
  expected HEAD, branch, zero remotes, and one reachable commit.

## Operational limitations

The checkpoint protects the benchmark state on this server. Because the payloads
are intentionally not committed to Git, a total disk failure would also destroy
the local checkpoint. Copy the entire checkpoint directory to separate reliable
storage if protection against host or disk loss is required.

After a host reboot, the recorded AppArmor profile may need to be loaded before
the restored containers can start. The profile source is included in the
checkpoint, but loading a host security policy still requires administrator
privileges.
