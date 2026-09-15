# Pre-experiment rollback checkpoint

Checkpoint ID: `pre-experiment-pr8073-20260912T050742Z`

This checkpoint captures the complete local state immediately before the first
SDD experiment for Scrapy PR 8073 / sample `600152fbc76dd5ba`.

The repository and HOME payloads still represent that original point. On
2026-09-14, the deployment-configuration payload was deliberately revised to
pin `model_reasoning_effort = "medium"` instead of `"high"`. Verification now
checks the archived profile, model catalog, launcher hashes, and metadata before
any restore begins.

## Captured state

- The immutable Scrapy baseline repository, including its `.git` directory.
- The OpenSpec, Spec Kit, and cc-sdd repositories, including their independent
  `.git` directories and initialized SDD integration files.
- The three independent Docker HOME volumes used by Codex CLI.
- The task's Compose, launcher, sandbox-policy, deployment-lock, provider,
  model-catalog, and egress-proxy configuration files.
- An offline Docker image archive for the fixed Agent and HAProxy images.
- Selected Git, image, container, and volume metadata in `checkpoint.json`.

The API key is deliberately excluded. Experiment logs are also excluded, so a
rollback never erases the audit trail produced after this checkpoint.

## Verify the checkpoint

```sh
./verify.sh
```

This checks every payload against `payloads/SHA256SUMS` and validates the
checkpoint metadata. Verification does not modify the deployment.

## Restore the checkpoint

Stop any experiment first. Then run:

```sh
DEEPSEEK_API_KEY_FILE=/absolute/path/outside/the/repository \
  ./restore.sh --yes
```

The restore operation:

1. verifies the checkpoint hashes and the formal-run lock;
2. stops the deployment while preserving its named volumes;
3. reloads the pinned images if the local Docker cache no longer has them;
4. writes a timestamped safety backup under `restore-backups/`;
5. restores all four repositories, three HOME volumes, and deployment files;
6. starts the isolated deployment and runs its normal validation path.

If the host has rebooted since deployment, reload the recorded AppArmor profile
before restoring. The restore script never reads, copies, prints, or archives the
API key; it passes the supplied path to the existing launcher only.

The binary payloads are server-local and ignored by Git. Keep this directory on
reliable storage if the experiment may modify or replace local Docker volumes.
