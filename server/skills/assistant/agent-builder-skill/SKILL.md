---
name: agent-builder-skill
description: How to use the Agent Builder tool's five canvas-mutation operations to inspect and grow your own toolset / skills / teammates / workflows mid-execution
allowed-tools: "agentBuilder"
metadata:
  author: machina
  version: "2.0"
  category: autonomous
---

# Agent Builder

You are connected to an **Agent Builder** node. It exposes ONE
LLM-callable tool, `agentBuilder`, which dispatches to FIVE
canvas-mutation operations via the `operation` field:

| `operation` value | Purpose |
|---|---|
| `inspect_canvas` | Read-only view of nodes, edges, and what's already wired to you. ALWAYS call this first. |
| `add_tool` | Spawn a tool node + wire it to your `input-tools` handle. |
| `add_skill` | Toggle a skill on your Master Skill (auto-creates one if missing). |
| `add_subagent` | Team-leads only -- spawn a delegate agent + wire to your `input-teammates`. |
| `create_workflow` | Persist a fresh empty workflow + return its id. Doesn't switch the user's view. |

Every call is `agentBuilder({operation: "<one-of-above>", ...op-specific-fields})`. There are no separate tools.

## The cardinal rule

**Call `agentBuilder({operation: "inspect_canvas"})` BEFORE any
mutation operation.** Without it you cannot tell whether a tool /
skill / subagent is already wired and will create duplicates.
Workflow becomes cluttered and your tool list confused.

The `inspect_canvas` summary tells you:
- which tools are already connected to your `input-tools`
- whether a Master Skill is wired to your `input-skill` (and what
  skills it has enabled)
- whether you have any teammate delegates (`input-teammates`)

Pick the smallest action that solves the problem. If the tool you
need is already on your canvas, USE IT -- don't add a duplicate.

## Soft-reload semantics (important)

The agent loop binds your tool list at the start of each invocation.
Tools / skills / teammates added mid-run **do NOT become callable
in the current run**. They become available on your **next
invocation** (next chat message, next workflow trigger, next call).

Each mutation returns a summary ending in "available on your next
turn". Take this literally. Do NOT loop trying to call something
you just added -- it isn't there yet. Tell the user what you added
and that they can use it on the next message.

## Operation reference

### `operation: "inspect_canvas"`

No additional fields. Returns:
```json
{
  "operation": "inspect_canvas",
  "nodes": [{ "id", "type", "label", "key_params" }, ...],
  "edges": [{ "source", "target", "source_handle", "target_handle" }, ...],
  "you": {
    "node_id": "agent-1",
    "incoming": [...], "outgoing": [...]
  },
  "summary": "5 nodes, 1 tool(s) wired to you (httpRequest), no skills."
}
```

API keys, prompts, and other secrets are **stripped** from
`key_params`. Only safe planner-relevant fields surface
(`provider`, `model`, `operation`, `url`, `query`).

### `operation: "add_tool"`

Required field: `node_type` (string).

Spawns a tool node and wires it to your `input-tools`. Allowed
types are anything registered with `component_kind="tool"` --
typically things like `httpRequest`, `braveSearch`,
`pythonExecutor`, etc. (NOT `agentBuilder` itself; NOT
`masterSkill`, which is managed via `add_skill` instead.)

If the tool has a paired teaching skill, the auto-add-skill
handler enables it too -- no separate `add_skill` call needed.

### `operation: "add_skill"`

Required field: `skill_folder` (string).

Enables a skill on your Master Skill. If you don't have a Master
Skill connected to `input-skill` yet, one is created and wired for
you. The skill folder must exist under `server/skills/**`
(e.g. `http-request-skill`, `memory-skill`, `python-skill`).

The skill's `SKILL.md` instructions become part of your system
message on your next turn.

### `operation: "add_subagent"`

Required field: `agent_type` (string).

**Team-leads only** (`orchestrator_agent`, `ai_employee`).
Spawns a specialized agent (`coding_agent`, `web_agent`,
`task_agent`, etc.) and wires it to your `input-teammates`
handle. The new agent appears as a `delegate_to_<name>` tool
on your next turn.

The new agent starts with empty configuration -- the user will
need to set its provider/model after the run. Mention this in your
response.

### `operation: "create_workflow"`

Required field: `workflow_name` (string).
Optional field: `workflow_description` (string).

Persists a fresh empty workflow with a single Start node and
returns its `workflow_id`. The user's current view does NOT
change; the frontend toasts a "Switch" link.

Use sparingly. Prefer mutating the current workflow over creating
new ones. Good cases for `create_workflow`:
- Templating / saving a solved pattern as a starting point.
- Splitting work into a separate workflow when the current one
  is getting too large.

## Worked example

User: "Search the web for current weather in Tokyo and tell me."

```
1. agentBuilder({operation: "inspect_canvas"})
   -> "1 nodes, no tool(s) wired to you, no skills."
   You see no web-search tool exists. Plan: add one.

2. agentBuilder({operation: "add_tool", node_type: "braveSearch"})
   -> "Added 'braveSearch' as a tool. Available on your next turn."

3. Reply to the user:
   "I've added a Brave Search tool to my toolset. Send me the same
    request on your next message and I'll search for the Tokyo
    weather."
```

DO NOT try to call `brave_search` in the same turn -- it's not in
your tool list yet. Just tell the user it's ready for next turn.

## What NOT to do

- **Don't skip `inspect_canvas`**. Always run it first; it's
  read-only and cheap.
- **Don't add a tool you already have**. The inspect summary tells
  you what's wired.
- **Don't loop on freshly-added tools**. They're not callable until
  next invocation.
- **Don't add `agentBuilder` to yourself via `add_tool`** (rejected
  -- avoids recursion; `agentBuilder` is excluded from the allowed
  tool types).
- **Don't spawn another team-lead** as a subagent (rejected --
  team-leads delegate to specialists, not to other team-leads).
- **Don't call `create_workflow`** unless the user explicitly asks
  to start a fresh workflow.
