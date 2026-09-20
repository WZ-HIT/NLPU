# Research: Nested Selector Type Inference

## Decision: Delegate root-based inference to parsel

**Rationale**: Parsel already distinguishes an existing root from text or body input and can infer JSON, HTML, XML, or text from that root. Scrapy's constructor currently intercepts a missing type before parsel runs, which overrides that inference for nested selectors.

**Alternatives considered**:

- Reimplement root inference in Scrapy: rejected because it duplicates parsel behavior and risks drift.
- Detect only JSON scalar roots: rejected because it fixes one example rather than the general nested-selector contract.
- Always leave the type unset: rejected because top-level response selectors rely on Scrapy's response-class defaults.

## Decision: Restrict response-derived defaults to omitted roots

**Rationale**: The existing "root not set" sentinel is the narrowest condition that distinguishes a constructor call for a response or raw input from parsel's call that supplies an already parsed nested root. This preserves response behavior while allowing parsel to infer the nested root type.

**Alternatives considered**:

- Change response defaults globally: rejected because it would alter established top-level selector behavior.
- Special-case JMESPath: rejected because nested selectors can be created by multiple parsel selection paths.

## Decision: Verify through the selector test module

**Rationale**: `tests/test_selector.py` already contains the flavor-detection and JMESPath tests that exercise top-level response type defaults and nested JSON/HTML interaction. The regression belongs there.

**Alternatives considered**:

- Response tests: rejected because the behavior is selector construction rather than response parsing.
- Loader tests: rejected because loaders consume selectors and do not define selector type inference.
