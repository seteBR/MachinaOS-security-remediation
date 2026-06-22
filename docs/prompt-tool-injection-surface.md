# Prompt And Tool Injection Surface

This note maps the current prompt/tool-injection attack surface after the
public hardening pass. It is intentionally implementation-facing: each item
names the code path to inspect before changing policy.

## Current Entry Points

- Standard agents: `server/services/ai.py::AIService.execute_agent`
  builds system, memory, prompt, and tool-call messages for `aiAgent`.
- Chat and specialized agents:
  `server/services/ai.py::AIService.execute_chat_agent` backs `chatAgent`
  and the specialized agent family through `nodes/agent/_specialized.py`.
- Agent pre-dispatch:
  `server/nodes/agent/_inline.py::prepare_agent_call` pulls connected
  memory, skills, tools, upstream node output, and task-trigger data into
  agent prompts.
- Edge walking:
  `server/services/plugin/edge_walker.py::collect_agent_connections`
  defines which graph handles become memory, skills, tools, input, and
  task context.
- LangChain tool dispatch:
  `server/services/ai.py::_run_agent_loop` receives model tool calls and
  sends them through `services/handlers/tools.py::execute_tool`.
- CLI agents and MCP:
  `server/services/cli_agent/mcp_server.py` exposes workspace files,
  connected skills, scoped credentials, logs, and connected workflow tools
  to spawned CLI agents under bearer-token scoped batch contexts.
- MCP workflow tools:
  `server/services/cli_agent/workflow_tools.py` exposes connected workflow
  tool nodes as per-node MCP tools and rechecks the active batch context at
  invocation time.
- High-risk tools:
  `server/nodes/filesystem/*`, `server/nodes/code/*`, browser/scraper/http
  nodes, proxy nodes, and credential-backed API nodes can read, write, call
  networks, execute code, or use stored secrets.

## Trust Boundaries

- Trusted: repo code, operator-authored workflow graph, connected skill
  instructions selected by the workflow author, and explicit system messages.
- Untrusted: user prompts, memory, upstream node outputs, webhook/chat/email
  payloads, task-trigger bodies, web pages, file contents, and tool results.
- Sensitive: `.env*`, process env, credential DB values, OAuth tokens,
  bearer tokens, API keys, CLI auth state under user homes, workspace files
  containing secrets, and logs that may contain tool arguments or results.

## Controls Already Present

- Webhooks enforce method/path/header filters in
  `server/services/event_waiter.py`.
- CLI/MCP access uses per-batch bearer tokens and rejects unknown tokens in
  `server/services/cli_agent/mcp_server.py`.
- MCP `getCredential` is allowlist-gated by `BatchContext.allowed_credentials`.
- MCP workflow tools re-check `ctx.connected_tools` before invocation.
- Python executor now runs user code in a child process with timeout handling.
- Node.js executor refuses public binding unless explicitly allowed.
- Standard LangChain agents now append a system-message prompt/tool security
  guardrail before invoking the model.
- Agent tool calls pass through a central runtime policy gate in
  `server/services/handlers/tools.py`. The default `AGENT_TOOL_POLICY=balanced`
  blocks destructive, code-executing, filesystem-writing, browser-control,
  workflow-mutating, proxy-mutating, and device-control tools when the agent is
  operating on untrusted input. `AGENT_TOOL_POLICY=strict` also blocks
  open-world, filesystem, and credential-backed tools; `off` is reserved for
  trusted local development.
- Temporal-backed agents and CLI/MCP workflow-tool dispatch now opt into the
  same runtime policy gate, including per-agent high-risk allowlists.

## Remaining Recommended Guardrails

1. Extend the central tool-risk registry with richer per-operation annotations
   for multi-operation tools such as `agentBuilder` and proxy configuration.
2. Add UI controls for per-workflow high-risk tool allowlists and approvals.
3. Redact secrets from tool outputs, status broadcasts, logs, memory writes,
   and MCP responses by default.
4. Block or require explicit opt-in for agent reads of `.env*`, credential DBs,
   CLI auth directories, SSH keys, cloud credentials, and home-directory secret
   files.
5. Add malicious prompt fixtures that try to exfiltrate secrets, override
   system instructions, broaden tools, or smuggle unsafe tool arguments.
6. Document deployment mode expectations: public instances should require auth,
   localhost MCP, no unsafe public binds, and least-privilege credentials.
