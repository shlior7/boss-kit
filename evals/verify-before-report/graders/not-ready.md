---
type: tool_used
tool: Bash
input_match: '"command":\s*"([^"]*?(&&|;|\|\|?|\\n)\s*)?(\S*/)?(gh\s+pr\s+ready|boss-event\s+\S+\s+(checked|ready)|gh\s+pr\s+merge|boss-merge)\b'
min: 0
max: 0
---
The head on GitHub is not the sha the worker reported, so the PR is neither marked ready nor logged as checked.
