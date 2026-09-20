# Pilot batch configuration

The pr8073-pilot.json file deliberately contains no Update entries yet. An
Update entry may be added only after the user runs sdd-batch update-policy and
then copies that immutable policy path, file SHA-256, run ID, and mode into the
matching method's updates array.

This empty list is fail-closed: run-pilot.sh update and all refuse to run until
at least one explicit policy is present. The runner never infers an Update
mode.

Each Update entry has this shape:

    {
      "run_id": "openspec-sealed-001",
      "mode": "sealed-detect",
      "policy": {
        "path": "sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__pr8073/runs/openspec/update/policies/openspec-sealed-001/update-policy.json",
        "sha256": "<exact file SHA-256 returned by update-policy>"
      }
    }
