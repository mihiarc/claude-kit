---
type: llm
weight: 1
---

Pass only if all of these hold:
- The answers file carries `overrides` with exactly one allow rule, `Bash(npm test)`, and nothing else under `overrides`. A wildcard or broader form (`Bash(npm test*)`, `Bash(npm test:*)`, `Bash(npm *)`) fails this.
- It adds no allow rule for `git push` or `gh pr merge`, and sets no model, effort level or permission mode.
- The preview it describes names the new allow rule and says the base's ask rules still apply.
- It doesn't propose, recommend or add any broader or further allow rule (such as a wildcard form or other npm commands). Saying that other forms still ask, or that the person can name more if they want them, is fine.
