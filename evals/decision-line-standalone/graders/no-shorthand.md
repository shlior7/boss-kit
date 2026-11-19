---
type: regex
pattern: '\bgo \d\b|\(\d\)|kit #\d+|Your move:(?![^\n]*(export|CSV|XLSX))[^\n]*#\d+'
flags: i
match: not_contains
---
No bare codes such as "go 1", "(0)", "kit #34", or a PR number on the Your move line without what the PR is.
