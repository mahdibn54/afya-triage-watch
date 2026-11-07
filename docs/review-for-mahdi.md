# Review notes for M (from B, Day 8)

Found while reviewing M's work against the code, the backlog and the live compose stack. Nothing here breaks a safety
invariant: scores and triggers stay in fixed code, the model can only add urgency, it gets no free text and no write
tool, and nothing changes before a nurse confirms. These are the items left for M. When one becomes a story, it goes
into `Afya_Tasks_BMAD.md` (the backlog stays the only task list) and the line here can be deleted.

## 5. Backlog entries that no longer match the code

Left (the others were fixed in E12-2):
- **E0-6 Notes:** "52 existing errors in `mcp/afya_mcp`" is out of date: `mypy afya_mcp` is clean now and `mypy afya_api`
  has 12 left (all LangGraph typing: `add_node`, `ainvoke`, `aget_state`). E0-6 is B's: update the count there, and
  decide whether mypy fails the CI or stays advisory.
- **E2-5** (B's story) is still `[ ]` but M did the binding (E5-9 notes, systemd override
  `OLLAMA_HOST=172.17.0.1:11434`, the api container reaches the model). B will close it, with the deviation that
  qwen3:30b-a3b was not pulled, unless M disagrees.
