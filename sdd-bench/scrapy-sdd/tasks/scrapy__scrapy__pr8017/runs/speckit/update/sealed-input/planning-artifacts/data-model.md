# Data Model: Typing the Remaining Exempt Test Modules

## Exempt Test Module

Represents one module entry under `[[tool.mypy.overrides]]`.

| Field | Meaning |
|-------|---------|
| `module` | Dotted mypy module name such as `tests.test_stats` |
| `candidate_path` | Repository-relative test file carrying the module's tests |
| `symbols` | Collectible test classes or functions in that file |
| `status` | Exempt until typed and verified |

## Candidate Set

| Dotted module | Candidate test file |
|---------------|---------------------|
| `tests.test_cmdline` | `tests/test_cmdline/__init__.py` |
| `tests.test_downloaderslotssettings` | `tests/test_downloaderslotssettings.py` |
| `tests.test_dupefilters` | `tests/test_dupefilters.py` |
| `tests.test_extension_statsmailer` | `tests/test_extension_statsmailer.py` |
| `tests.test_extension_throttle` | `tests/test_extension_throttle.py` |
| `tests.test_linkextractors` | `tests/test_linkextractors.py` |
| `tests.test_logformatter` | `tests/test_logformatter.py` |
| `tests.test_mail` | `tests/test_mail.py` |
| `tests.test_pqueues` | `tests/test_pqueues.py` |
| `tests.test_scheduler_base` | `tests/test_scheduler_base.py` |
| `tests.test_settings` | `tests/test_settings/__init__.py` |
| `tests.test_squeues` | `tests/test_squeues.py` |
| `tests.test_squeues_request` | `tests/test_squeues_request.py` |
| `tests.test_stats` | `tests/test_stats.py` |

## State Transition

`exempt` → `typed locally` → `mypy clean` → `behavior verified` → `exemption removed`.
