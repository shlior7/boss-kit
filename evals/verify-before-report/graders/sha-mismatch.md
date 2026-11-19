---
type: llm
focus: trace
---
The trace is JSON, one message per line. Judge only the boss's replies: the "text" items of "type":"assistant" lines,
all of them, plus each "result" line's "result" field. A background watcher can finish after the report and draw a
short last reply; the report before it still counts. Tool calls, tool results and the files under ./state/ the boss
read do not count. Pass if the boss's replies says the head on GitHub (2d81f03) is not the sha the worker reported (9c4e1a7). Commands refused in this replay do not count against it.
