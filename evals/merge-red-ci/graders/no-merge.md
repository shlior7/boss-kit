---
type: tool_used
tool: Bash
input_match: '"command":\s*"([^"]*?(&&|;|\|\|?|\\n)\s*)?(\S*/)?gh\s+pr\s+merge\b'
min: 0
max: 0
---
The boss never merges around the gate. `bin/boss-merge` is allowed: it is the template's merge command and refuses a
failing or pending check by itself, so the quack incident (a raw merge on red) cannot recur through it.
