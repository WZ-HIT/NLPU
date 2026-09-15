# DeepSeek-V4.1-Flash/high pre-experiment rollback checkpoint

Checkpoint ID: `pre-experiment-pr8073-flash-high-20260914T064502Z`

This checkpoint combines the verified pre-experiment Scrapy PR 8073 / sample
`600152fbc76dd5ba` repository and independent HOME states with a deployment
configuration fixed to API model ID `deepseek-flash` and reasoning effort
`high`. DeepSeek identifies this moving API alias as DeepSeek-V4.1-Flash as of
2026-09-10.

The prior Pro/medium checkpoint remains separate. Verification checks the
archived Flash profile, model catalog, launcher hashes, metadata, and all payload
checksums before any restore begins.

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
