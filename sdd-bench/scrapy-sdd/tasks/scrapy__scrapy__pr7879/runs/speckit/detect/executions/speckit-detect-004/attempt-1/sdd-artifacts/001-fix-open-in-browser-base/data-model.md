# Data Model: Fix open_in_browser base insertion without a head

## Entities

### HTML Response

- **URL**: The base URL used for relative resources.
- **Body**: HTML bytes preserved for preview.
- **Response type**: Determines whether base insertion applies.

### Head Marker

- **Presence**: Whether a real head element exists outside comments.
- **Boundary**: The position immediately after the opening head tag when present.

### Base Element

- **Presence**: Whether an effective base already exists outside comments.
- **Value**: The response URL used for insertion.

## Relationships

- An HTML response may contain zero or one real effective base element.
- A base element is inserted inside a real head element when one exists.
- A headless HTML response receives a fallback effective base section.
- Plain text responses have no base relationship.

## Validation Rules

- Do not count commented markup as a real head or base.
- Do not insert a second effective base.
- Preserve all non-insertion bytes.
- Do not alter the response object or write persistent data.
