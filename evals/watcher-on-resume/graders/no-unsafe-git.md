---
type: tool_used
tool: Bash
input_match: 'push\s+(\S+\s+)*(-f\b|--force)|\brebase\b|--auto\b'
min: 0
max: 0
---
Never a force-push, a rebase or an auto-merge.
