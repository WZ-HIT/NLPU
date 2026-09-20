# Pre-experiment rollback checkpoint

This directory is a rollback point for one batch (pilot) task, taken before any
SDD stage ran. `checkpoint.json` names the task, the Scrapy base SHA it was
provisioned on, and the payload that holds each part of the recorded state.

It differs in shape from the hand-made checkpoints next to it, and the
difference is a property of the task generation, not a simplification:

| | template task (`scrapy__scrapy__8073__test_only__...`) | pilot task |
|---|---|---|
| containers | three, long-lived | one per run, torn down by the harness |
| HOME | named Docker volumes | `tmpfs` at `/run/sdd-home` |
| `/workspace` | `runs/<variant>/scrapy` | `runs/<method>/detect/workspace` |
| restore ends by | starting the deployment again | starting nothing |

## Captured state

- The immutable Scrapy baseline repository for this base SHA, including `.git`.
- The OpenSpec, Spec Kit and cc-sdd repositories, including their independent
  `.git` directories and initialized SDD integration files.
- The task's deployment configuration: Compose files, stage policy, deployment
  lock, initialization inputs and the frozen `initial-workspaces.json`.
- An offline archive of the pinned Agent and HAProxy images.

`home_volumes` is empty, and that is the record, not an omission: a pilot task's
HOME is a tmpfs and is destroyed with its container. Nothing inside it can be
carried across a run.

`detect_planning_artifacts` is the same kind of record. It names
`runs/<method>/detect/planning-artifacts`, which Detect's Compose service binds
into the container at the method's own spec directory (`/workspace/specs` for
Spec Kit, `/workspace/openspec/changes` for OpenSpec, `/workspace/.kiro/specs`
for cc-sdd). The bind is rendered with `create_host_path: false`, so the
directory has to exist before Compose runs — otherwise the container is not
created at all. It holds no bytes at the moment captured here, so it is recorded
rather than packaged, and a restore recreates it empty.

The API key is deliberately excluded, and so are `runs/*/{executions,output,audit}`.
Those are the evidence produced *after* the moment recorded here; a rollback that
erased them would destroy the audit trail it exists to protect.

Two things are moved rather than left in place, into `restore-backups/`:

- `runs/<method>/update/sealed-input`, the Detect seal. Sealing is one-way —
  `batch/stages.py` refuses to seal a second time while it exists — so a restore
  that put the workspace back but left the seal would restore the files without
  restoring the ability to run Detect, which is what a rollback is for.
- whatever Detect wrote into `planning-artifacts`, so the next run starts from
  an empty mount point instead of inheriting the previous run's planning.

Neither is deleted.

## Verify

```sh
./verify.sh
```

Checks every payload against `payloads/SHA256SUMS` and validates the metadata,
including that every payload the document references is both listed and present.
It does not touch Docker, so it answers "is this rollback point intact" on a host
with no daemon and no images loaded.

## Restore

```sh
./restore.sh --yes          # add --dry-run to see the plan first
```

Restore:

1. verifies the checkpoint, and refuses to continue if it does not pass;
2. stops any stack still labelled with this task's Compose project prefix,
   including exited containers and their leftover networks and volumes;
3. moves the current repositories, the Detect seal and the Detect mount points
   aside under `restore-backups/<UTC>/` — nothing is deleted, so a failed
   restore is reversible by hand;
4. extracts the recorded repositories and configuration, and recreates each
   Detect mount point empty;
5. re-checks each restored workspace against the digest in
   `initial-workspaces.json` using the harness's own function from
   `batch/stages.py`, and checks that every mount point is back and empty and
   no seal survives — the two facts that decide whether Detect can run again.

It does not start containers and does not open the API key: a pilot task's
containers are created by the run, not by a restore.

Binary payloads are server-local and ignored by Git. Keep this directory on
reliable storage.
