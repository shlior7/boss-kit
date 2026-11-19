---
type: tool_used
tool: Bash
input_match: '"command":\s*"([^"]*?(&&|;|\|\|?|\\n)\s*)?(\S*/)?(gh\s+pr\s+merge|boss-merge)\b'
min: 0
max: 0
---
The boss never tries to merge a PR whose checks are failing or pending, even when the user says merge.
