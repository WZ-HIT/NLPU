# Data Model: Nested Selector Type Inference

## Selector Construction Input

- **Fields**: optional response, optional text, optional body, optional existing root, optional explicit type
- **Validation**: response and text remain mutually exclusive; an existing root and text are not combined by Scrapy
- **Relationship**: supplies the values used to determine the selector representation

## Root Sentinel

- **Fields**: omitted-root marker
- **Validation**: identity comparison distinguishes omission from every legitimate root value, including `None` where allowed
- **Relationship**: controls whether Scrapy applies response-derived type defaults

## Selector Type

- **Fields**: `html`, `xml`, `json`, `text`, or unset
- **Validation**: explicit types remain valid; response-derived defaults apply only to top-level response construction; parsel owns inference when both type and root are supplied
- **State transition**: unset -> inferred type during selector construction

## Response

- **Fields**: response class and decoded body
- **Validation**: supported subclasses retain their existing default selector type
- **Relationship**: an explicit response participates in top-level type derivation but is not required for nested selectors
