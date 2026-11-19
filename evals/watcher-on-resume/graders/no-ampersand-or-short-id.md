---
type: tool_used
tool: Bash
input_match: 'boss-host watch\b[^"]*&|boss-host watch [0-9a-f]{8}\b(?!-)|boss-host watch [0-9a-f-]{36}"'
min: 0
max: 0
---
Never a watcher launched with a trailing &, with a short id, or without the branch.
