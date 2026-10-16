# Agent orchestration, model routing and resource governance

Scope: how AI coding agents work in this repository. Process rules are in [../../AGENTS.md](../../AGENTS.md); this file
adds delegation, model routing, budgets and checkpoints. Each rule is marked **[enforced]** when a tool setting makes
it technically binding, or **[policy]** when it relies on the agent following it. Nothing here claims more enforcement
than the listed setting provides.

## 1. Tools present on this machine (verified 2026-10-15)

| Tool | Status | Instruction discovery |
|---|---|---|
| Claude Code (VS Code extension) | in use; the `claude` CLI is not on PATH | reads `CLAUDE.md` (which imports `AGENTS.md`), project subagents in `.claude/agents/*.md`, project settings `.claude/settings.json` |
| Codex CLI | **not installed** (`codex` not found) | Codex reads `AGENTS.md` natively; no Codex-specific configuration is created until it is installed and its version is checked |

Sources for Claude Code formats: official docs (sub-agents, permissions, memory/imports, model configuration). Only
documented keys are used: subagent frontmatter `name`, `description`, `tools`, `model`, `maxTurns`; settings
`permissions.deny` / `permissions.ask`.

## 2. Roles

One **orchestrator** (the main session) owns the plan, integration, verification and the final report. Specialists are
created only when they save real work or add independence:

| Role | When | Access | Project definition |
|---|---|---|---|
| Repository scout | broad search over many files where only the conclusion matters | read-only | `.claude/agents/repo-scout.md` |
| Data reviewer | independent review of a schema/migration/data change against the live-DB copy and invariants | read-only + read-only shell checks on copies | `.claude/agents/data-reviewer.md` |
| Docs lookup | questions about Claude Code / API features | read-only web docs | built-in `claude-code-guide` |
| Implementer / test runner | only for a disjoint module with a clear contract; otherwise the orchestrator edits | edits limited to the assigned files | none (ad hoc, contract below) |

**[policy]** At most **two** specialists run at the same time. No agent for trivial tasks (one known file, one fact).
Specialists never create further agents, never widen scope, and stop when the contract's output is delivered. Two
agents never edit the same file; edits are owned per module. **[enforced]** Read-only roles are defined with a `tools`
list without `Edit`/`Write`.

## 3. Task contract (required for every delegation) [policy]

```
Task ID:            <phase>-<n>
Objective / scope:  one sentence; what is out of scope
Files / modules:    exact paths (read) and owned paths (edit, if any)
Input context:      facts already verified (do not re-derive)
Constraints:        AGENTS.md section 4/5/8 + task specifics
Model tier:         T1 / T2 / T3 (section 4)
Budget:             max turns (maxTurns) and expected size of the answer
Expected output:    evidence (paths, line numbers, command output), changed files, test results,
                    unresolved issues, completion status DONE / PARTIAL / BLOCKED
Validation:         how the orchestrator will verify the result
Stop when:          the output is delivered or a blocker is hit (report it; do not work around it)
```

## 4. Model routing

Logical tiers map to model aliases accepted by Claude Code (`haiku`, `sonnet`, `opus`, or `inherit`). Prices, quotas
and context sizes are **not** recorded here because they cannot be verified from this machine.

| Tier | Work | Default alias |
|---|---|---|
| T1 | inventory, search, formatting, mechanical edits, deterministic checks, simple docs | `haiku` |
| T2 | bounded features, normal debugging, integration tests, moderate refactoring, doc lookups | `sonnet` |
| T3 | architecture, security-sensitive code (OAuth, secrets), data migrations, hard root-cause analysis, final integration | the main session model (`inherit`) |

* **[enforced]** The project subagents pin their tier with the `model` frontmatter field (scout = `haiku`, data reviewer =
  `sonnet`), and cap their turns with `maxTurns`. The per-call `model` override can still change it; the orchestrator
  does not use that override except for an escalation that meets the rule below.
* **[policy]** Escalate one tier only with evidence that the current tier failed for a capability reason (wrong
  result verified, not merely slow), and record the reason in the checkpoint. No silent escalation; no escalation
  because a model is unavailable (report it instead).
* **[policy]** Prefer deterministic scripts (PowerShell/Python in the session scratchpad) over model tokens for
  predictable work: hashing, schema dumps, package verification, DB copies, row counts.

## 5. Resource budget

* **[policy]** Target: a batch uses at most 50 % of the session and weekly allowance visible to the user. Claude Code does
  not expose usage figures to the agent in this environment, so the limit cannot be measured or enforced technically;
  the agent keeps work bounded instead: no repeated audits of completed phases, no speculative refactors, at most two
  concurrent specialists, `maxTurns` on project subagents.
* **[policy]** Retries: a failing command or test is retried at most **twice** after a diagnosed change; an external
  dependency (credentials, IAM, approval) is reported as a blocker after the first clear failure, never retried in a loop.
* **[policy]** Long outputs go to files (logs, reports); the conversation receives summaries with paths.

## 6. Checkpoints and resume

* Before editing a group of files, save a ZIP of the touched source tree in `checkpoints/` (e.g.
  `source-<version>-before-<change>-<time>.zip`).
* Keep `docs/CHECKPOINT.md` current: batch name, phases with status (DONE / IN PROGRESS / BLOCKED), evidence paths,
  and the next step. On resume, verify the live state (section 2 of AGENTS.md) instead of repeating completed phases.
* The final report in `reports/` closes the batch.

## 7. Technical enforcement in `.claude/settings.json` [enforced, within limits]

The project settings deny file-tool access that would edit live data or read credentials, and ask before commands
that change external or irreversible state. Limits that remain: deny rules for `Edit`/`Write` do not stop a shell
command from writing the same file, and shell rules match command text, not intent. These rules are guard rails, not
a security boundary; the policy rules above still apply.
