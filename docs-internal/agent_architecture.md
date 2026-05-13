# AI Agent Architecture: Skill Injection & Tool Execution

Detailed architecture reference for how AI Agent (`aiAgent`) and Chat Agent (`chatAgent`) discover skills and tools from connected nodes, inject them into the LLM prompt, and execute tools via LangGraph.

> **Related Documentation:**
> - [AI Tool Node Guide](./ai_tool_node_creation.md) - Creating dedicated AI Agent tool nodes
> - [Dual-Purpose Tool Guide](./dual_purpose_tool_node_creation.md) - Nodes that work as workflow nodes AND AI tools
> - [Specialized Agent Guide](./specialized_agent_node_creation.md) - Creating specialized AI agents
> - [CLAUDE.md](../CLAUDE.md) - Project overview and full node inventory

## Table of Contents

1. [End-to-End Data Flow](#end-to-end-data-flow)
2. [LangGraph Agent Graph](#langgraph-agent-graph)
3. [Skill Injection Pipeline](#skill-injection-pipeline)
4. [Tool Building Pipeline](#tool-building-pipeline)
5. [Tool Execution Flow](#tool-execution-flow)
6. [Memory Integration](#memory-integration)
7. [execute_agent vs execute_chat_agent](#execute_agent-vs-execute_chat_agent)

---

## End-to-End Data Flow

```
User clicks "Run" on AI Agent
        |
        v
useExecution.executeNode()               client/src/hooks/useExecution.ts
  Sends ALL workflow nodes + edges
        |
        v
WebSocket: handle_execute_node()          server/routers/websocket.py
  Passes nodes[], edges[] to WorkflowService
        |
        v
WorkflowService.execute_node()            server/services/workflow.py
  Builds context = {nodes, edges, session_id, workflow_id}
  Calls NodeExecutor.execute()
        |
        v
NodeExecutor._dispatch()                  server/services/node_executor.py
  Handler registry lookup via functools.partial
  Dispatches to handle_ai_agent() or handle_chat_agent()
        |
        v
_collect_agent_connections()              server/services/handlers/ai.py
  Scans edges where target == node_id
  Groups by targetHandle into 4 buckets:
    input-memory  -> memory_data
    input-skill   -> skill_data[]
    input-tools   -> tool_data[]
    input-main    -> input_data
        |
        v
AIService.execute_agent()                 server/services/ai.py
  1. Inject skills into system message
  2. Build LangChain StructuredTools from tool_data
  3. Construct LangGraph with agent + tools nodes
  4. Run graph with initial messages
  5. Save memory, return result
        |
        v
LangGraph StateGraph execution
  agent node <-> tool node loop
  LLM decides when to call tools
        |
        v
Result broadcast via WebSocket
```

### Key Files

| File | Responsibility |
|------|---------------|
| `client/src/hooks/useExecution.ts` | Frontend execution trigger, sends nodes + edges |
| `server/routers/websocket.py` | WebSocket handler `handle_execute_node()` |
| `server/services/workflow.py` | Facade, builds context, delegates to NodeExecutor |
| `server/services/node_executor.py` | Handler registry, dispatches via `functools.partial` |
| `server/services/handlers/ai.py` | `_collect_agent_connections()`, `handle_ai_agent()`, `handle_chat_agent()` |
| `server/services/ai.py` | `AIService` -- LangGraph construction, skill injection, tool building |
| `server/services/handlers/tools.py` | `execute_tool()` -- dispatch router for all tool types |
| `server/services/skill_loader.py` | `SkillLoader` -- filesystem/DB skill discovery and loading |

---

## LangGraph Agent Graph

### AgentState Schema

Defined in `server/services/ai.py:386-402`:

```python
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]  # Accumulates via operator.add
    tool_outputs: Dict[str, Any]
    pending_tool_calls: List[Dict[str, Any]]
    iteration: int
    max_iterations: int
    should_continue: bool
    thinking_content: Optional[str]  # Accumulated across iterations
```

Key design: `Annotated[..., operator.add]` on messages means new messages are **appended** to state, not replaced.

### Graph Topology

Built by `build_agent_graph()` in `server/services/ai.py:646-709`:

```
WITH TOOLS:
    START --> agent --> should_continue() --> tools --> agent --> ... --> END
                            |
                            +--> END (no tool calls or max iterations)

WITHOUT TOOLS:
    START --> agent --> END
```

```python
def build_agent_graph(chat_model, tools=None, tool_executor=None):
    graph = StateGraph(AgentState)

    # Bind tools to model (makes LLM aware of tool schemas)
    model_with_tools = chat_model
    if tools:
        model_with_tools = chat_model.bind_tools(tools)

    # Add nodes
    graph.add_node("agent", create_agent_node(model_with_tools))
    graph.set_entry_point("agent")

    if tools and tool_executor:
        graph.add_node("tools", create_tool_node(tool_executor))
        graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "end": END})
        graph.add_edge("tools", "agent")  # Loop back

    return graph.compile()
```

### Agent Node

`create_agent_node()` in `server/services/ai.py:509-584`:

1. Receives `state["messages"]` (accumulated conversation)
2. Filters empty messages (prevents API errors for Gemini/Claude)
3. Invokes LLM: `response = chat_model.invoke(filtered_messages)`
4. Extracts thinking content (Claude content_blocks, Gemini metadata, Groq additional_kwargs)
5. Checks `response.tool_calls` -- if present, sets `should_continue=True`
6. Returns updated state with `[response]` appended via `operator.add`

### Tool Node

`create_tool_node()` in `server/services/ai.py:587-631`:

```python
async def tool_node(state: AgentState) -> Dict[str, Any]:
    tool_messages = []
    for tool_call in state.get("pending_tool_calls", []):
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_id = tool_call.get("id", "")

        try:
            result = await tool_executor(tool_name, tool_args)
        except Exception as e:
            result = {"error": str(e)}

        tool_messages.append(ToolMessage(
            content=json.dumps(result, default=str),
            tool_call_id=tool_id,
            name=tool_name
        ))

    return {"messages": tool_messages, "pending_tool_calls": []}
```

- Iterates all pending tool calls from the LLM
- Calls the `tool_executor` callback (closure built in `execute_agent()`)
- Wraps results as `ToolMessage` objects with matching `tool_call_id`
- Errors are caught and returned as `{"error": ...}` -- the LLM sees the error and can retry or respond

### Routing Logic

`should_continue()` in `server/services/ai.py:634-643`:

```python
def should_continue(state: AgentState) -> str:
    if state.get("should_continue", False):
        if state.get("iteration", 0) < state.get("max_iterations", 10):
            return "tools"
    return "end"
```

Routes to `"tools"` when:
- LLM returned tool calls (`should_continue=True`)
- AND iteration count < `max_iterations` (default 10)

---

## Skill Injection Pipeline

### 1. Edge Scanning

In `_collect_agent_connections()` (`server/services/handlers/ai.py:14-49`), all edges targeting the agent node are scanned:

```python
for edge in edges:
    if edge.get('target') != node_id:
        continue

    target_handle = edge.get('targetHandle')
    source_node_id = edge.get('source')

    if target_handle == 'input-skill':
        # Collect skill data...
```

### 2. Regular Skill Nodes

For standard skill nodes (claudeSkill, whatsappSkill, etc.), a single entry is created:

```python
skill_entry = {
    'node_id': source_node_id,
    'node_type': skill_type,           # e.g., 'whatsappSkill'
    'skill_name': skill_params.get('skillName', skill_type),
    'parameters': skill_params,         # All node parameters from DB
    'label': source_node.get('data', {}).get('label', skill_type)
}
skill_data.append(skill_entry)
```

### 3. Master Skill Expansion

When the connected skill is a `masterSkill`, its `skillsConfig` parameter is expanded into N individual entries:

```python
if skill_type == 'masterSkill':
    skills_config = skill_params.get('skillsConfig', {})
    # Structure: {'whatsapp-skill': {'enabled': True, 'instructions': '...'}, ...}

    for skill_key, skill_cfg in skills_config.items():
        if not skill_cfg.get('enabled', False):
            continue  # Skip disabled skills

        # DB-first: use stored instructions
        instructions = skill_cfg.get('instructions', '')

        if not instructions:
            # Fallback: load from SKILL.md on disk
            skill = skill_loader.load_skill(skill_key)
            if skill:
                instructions = skill.instructions

        skill_data.append({
            'node_id': f"{source_node_id}_{skill_key}",  # Unique composite ID
            'node_type': 'masterSkill',
            'skill_name': skill_key,
            'parameters': {'instructions': instructions, 'skillName': skill_key},
            'label': skill_key
        })
```

One Master Skill node with 5 enabled skills produces 5 separate `skill_data` entries.

### 4. SkillLoader Architecture

Defined in `server/services/skill_loader.py:38+`:

```
SkillLoader
├── _skill_dirs: [server/skills/, .machina/skills/]
├── _registry: Dict[name -> SkillMetadata]    # Metadata only (~100 tokens each)
├── _cache: Dict[name -> Skill]               # Full content (lazy-loaded)
│
├── scan_skills()           # rglob("SKILL.md") across all dirs, parses frontmatter
├── load_skill(name)        # Loads full content: cache -> registry -> filesystem
├── get_registry_prompt()   # Generates "## Available Skills" for system message
└── get_skill_instructions()# Shortcut for load_skill().instructions
```

**`scan_skills()`** (`skill_loader.py:63-88`):
- Iterates `_skill_dirs`, uses `rglob("SKILL.md")` for recursive discovery
- Parses YAML frontmatter for each file (`_parse_skill_metadata`)
- Populates `_registry` with `SkillMetadata` (name, description, allowed_tools, path)

**`load_skill(name)`** (`skill_loader.py:174-249`):
1. Check `_cache` -- return immediately if cached
2. Look up `_registry[name]` -- fail if not registered
3. Read `SKILL.md`, strip frontmatter, extract markdown body as `instructions`
4. Load optional `scripts/` and `references/` directories
5. Cache and return `Skill` dataclass

**SKILL.md frontmatter parsing** (`skill_loader.py:126-172`):
```yaml
---
name: http-skill                    # Lowercase with hyphens, validated by regex
description: Make HTTP requests...  # Brief description for LLM visibility
allowed-tools: http-request         # Space-delimited tool names
metadata:
  author: machina
  version: "2.0"
---
```

### 5. System Message Injection

In `execute_agent()` and `execute_chat_agent()` within `server/services/ai.py`:

```python
if skill_data:
    skill_loader = get_skill_loader()
    skill_loader.scan_skills()

    # Extract skill names from collected data
    skill_names = []
    for skill_info in skill_data:
        skill_name = skill_info.get('skill_name') or ...
        skill_names.append(skill_name)

    # Generate structured skill listing
    skill_prompt = skill_loader.get_registry_prompt(skill_names)
    if skill_prompt:
        system_message = f"{system_message}\n\n{skill_prompt}"
```

### 6. Registry Prompt Output

`get_registry_prompt()` in `skill_loader.py:311-341` generates:

```
## Available Skills

You have access to the following skills. When a user's request matches
a skill's purpose, activate it to help them.

- **http-skill**: Make HTTP requests to external APIs
  - Tools: http-request
- **whatsapp-skill**: Send and receive WhatsApp messages
  - Tools: whatsapp-send, whatsapp-db
- **maps-skill**: Location services via Google Maps

To use a skill, identify when the user's request matches its purpose
and apply the skill's instructions.
```

This text is appended to the system message. The full SKILL.md body (instructions) is available via individual skill entries but the registry prompt provides the high-level listing.

### 7. allowed-tools

- **Parsed** from SKILL.md frontmatter as space-delimited list
- **Included** in registry prompt as informational text for the LLM
- **NOT enforced** in code -- the LLM can call any tool connected to `input-tools`
- Purpose: guides the LLM on which tools are relevant to each skill

---

## Tool Building Pipeline

### 1. Tool Data Collection

In `_collect_agent_connections()`, edges targeting `input-tools` are collected:

```python
elif target_handle == 'input-tools':
    tool_params = await database.get_node_parameters(source_node_id)
    tool_entry = {
        'node_id': source_node_id,
        'node_type': tool_type,       # 'calculatorTool', 'pythonExecutor', etc.
        'parameters': tool_params,
        'label': source_node.get('data', {}).get('label', tool_type),
        'connected_services': []       # Populated for androidTool only
    }
```

For `androidTool` (toolkit pattern), edges are scanned a second time to find Android service nodes connected to the toolkit, populating `connected_services`.

### 2. Tool Name and Schema Mapping

`_build_tool_from_node()` in `server/services/ai.py` maps each node type:

| Node Type | Tool Name | Pydantic Schema |
|-----------|-----------|-----------------|
| `calculatorTool` | `calculator` | `CalculatorSchema(operation, a, b)` |
| `currentTimeTool` | `get_current_time` | `CurrentTimeSchema(timezone)` |
| `timer` | `timer` | `TimerSchema(delay, unit)` |
| `duckduckgoSearch` | `web_search` | `DuckDuckGoSearchSchema(query, max_results)` |
| `pythonExecutor` | `python_code` | `PythonCodeSchema(code)` |
| `javascriptExecutor` | `javascript_code` | `JavaScriptCodeSchema(code)` |
| `httpRequest` | `http_request` | `HttpRequestSchema(url, method, body)` |
| `whatsappSend` | `whatsapp_send` | `WhatsAppSendSchema(recipient_type, phone, message_type, message, ...)` |
| `whatsappDb` | `whatsapp_db` | `WhatsAppDbSchema(operation, chat_id, query, limit)` |
| `braveSearch` | `brave_search` | `BraveSearchSchema(query, max_results, country, safe_search)` |
| `serperSearch` | `serper_search` | `SerperSearchSchema(query, max_results, search_type, country)` |
| `perplexitySearch` | `perplexity_search` | `PerplexitySearchSchema(query, model, search_recency_filter)` |
| `gmaps_locations` | `geocode` | `GeocodeSchema(address)` |
| `gmaps_nearby_places` | `nearby_places` | `NearbyPlacesSchema(location, type, radius)` |
| `androidTool` | `android_device` | `AndroidToolSchema(service_id, action, parameters)` |
| Direct Android services | `android_<service>` | `AndroidServiceSchema(action, parameters)` |
| `aiAgent` | `delegate_to_ai_agent` | `DelegateToAgentSchema(task, context)` |
| Specialized agents | `delegate_to_<type>` | `DelegateToAgentSchema(task, context)` |

### 3. StructuredTool Construction

```python
# Lookup or generate schema
schema = _get_tool_schema(node_type, schema_params)

# Create LangChain tool with placeholder function
tool = StructuredTool.from_function(
    name=tool_name,
    description=tool_description,
    func=lambda **kwargs: kwargs,    # Placeholder -- actual execution via callback
    args_schema=schema               # Pydantic BaseModel subclass
)

# Store config for execution
tool_configs[tool.name] = {
    'node_id': node_id,
    'node_type': node_type,
    'parameters': node_params,
    'connected_services': connected_services
}
```

### 4. Database Schema Override

The Tool Schema Editor UI stores custom schemas in the `tool_schemas` table. If a custom schema exists for a node, it takes priority over the default:

```python
db_schema = await self.database.get_tool_schema(node_id)
if db_schema:
    tool_name = db_schema.tool_name
    tool_description = db_schema.tool_description
    schema = self._build_schema_from_config(db_schema.schema_config)
```

### 5. Tool Binding

After all tools are built, they are bound to the LLM model via LangChain:

```python
model_with_tools = chat_model.bind_tools(tools)
```

This makes the LLM aware of all available tool schemas during generation. The LLM decides when to call tools based on the user's request and tool descriptions.

---

## Tool Execution Flow

### 1. Tool Executor Callback

Built as a closure in `execute_agent()` / `execute_chat_agent()`:

```python
async def tool_executor(tool_name: str, tool_args: Dict) -> Any:
    config = tool_configs.get(tool_name, {})
    tool_node_id = config.get('node_id')

    # Broadcast "executing" status to tool node (UI glow animation)
    await broadcaster.update_node_status(tool_node_id, "executing", {...})

    # Inject services for nested delegation
    config['ai_service'] = self
    config['database'] = self.database
    config['nodes'] = context.get('nodes', [])
    config['edges'] = context.get('edges', [])

    # Dispatch to handler
    result = await execute_tool(tool_name, tool_args, config)

    # Broadcast "success" status
    await broadcaster.update_node_status(tool_node_id, "success", {...})

    return result
```

### 2. Dispatch Router

`execute_tool()` in `server/services/handlers/tools.py` routes by `node_type`:

```python
async def execute_tool(tool_name, tool_args, config):
    node_type = config.get('node_type', '')

    if node_type == 'calculatorTool':        return await _execute_calculator(tool_args)
    elif node_type == 'pythonExecutor':       return await _execute_python_code(tool_args, config['parameters'])
    elif node_type == 'javascriptExecutor':   return await _execute_javascript_code(tool_args, config['parameters'])
    elif node_type == 'currentTimeTool':      return await _execute_current_time(tool_args)
    elif node_type == 'timer':               return await handle_timer(...)
    elif node_type == 'duckduckgoSearch':      return await _execute_duckduckgo_search(tool_args)
    elif node_type == 'braveSearch':          return await _execute_brave_search_tool(tool_args, config['parameters'])
    elif node_type == 'serperSearch':         return await _execute_serper_search_tool(tool_args, config['parameters'])
    elif node_type == 'perplexitySearch':     return await _execute_perplexity_search_tool(tool_args, config['parameters'])
    elif node_type == 'whatsappSend':         return await _execute_whatsapp_send(tool_args)
    elif node_type == 'whatsappDb':           return await _execute_whatsapp_db(tool_args)
    elif node_type == 'androidTool':          return await _execute_android_toolkit(tool_args, config)
    elif node_type in ANDROID_SERVICE_TYPES:  return await _execute_android_service(tool_args, config)
    elif node_type == 'gmaps_locations':      return await _execute_geocoding(tool_args)
    elif node_type == 'gmaps_nearby_places':  return await _execute_nearby_places(tool_args)
    elif node_type in DELEGATED_AGENT_TYPES:  return await _execute_delegated_agent(tool_args, config)
    else:                                     return await _execute_generic(tool_args, config)
```

### 3. Status Broadcasting

Three-level broadcasting ensures the UI shows tool execution state:

```
1. Agent node:  "executing_tool" phase with tool_name
2. Tool node:   "executing" status (cyan glow animation on SquareNode)
3. Completion:  "success" or "error" on tool node
```

For the Android Toolkit, status is broadcast to the **connected service node** (e.g., Battery Monitor), not the toolkit itself -- so the user sees the actual service node glowing.

### 4. Dual-Purpose Tools

Nodes like `pythonExecutor`, `whatsappSend`, `gmaps_locations` work as both workflow nodes and AI tools. The handler prioritizes LLM-provided args, falling back to node parameters:

```python
async def _execute_python_code(args, node_params):
    # LLM args take priority, node params as fallback
    code = args.get('code', '') or node_params.get('code', '')
```

### 5. Android Toolkit (Sub-Node Pattern)

```
[Battery Monitor] --+
[WiFi Automation] --+--> [Android Toolkit] --(tools)--> [AI Agent]
[Location] --------+
```

The LLM sees a single `android_device` tool. It specifies `service_id` to choose which connected service to invoke:

```python
async def _execute_android_toolkit(args, config):
    service_id = args.get('service_id')
    connected_services = config.get('connected_services', [])

    # Find matching service by service_id
    target = next((s for s in connected_services if s['service_id'] == service_id), None)

    # Broadcast to connected service node (not toolkit)
    await broadcaster.update_node_status(target['node_id'], "executing", {...})

    # Execute via AndroidService
    result = await android_service.execute_service(service_id=service_id, action=action, ...)
```

### 6. Direct Android Service Tools

Android service nodes can also connect directly to `input-tools` (bypassing the toolkit). The handler maps camelCase node types to snake_case service IDs:

```python
SERVICE_ID_MAP = {
    'batteryMonitor': 'battery',
    'wifiAutomation': 'wifi_automation',
    'bluetoothAutomation': 'bluetooth_automation',
    'location': 'location',
    'appLauncher': 'app_launcher',
    # ... 16 total mappings
}
```

### 7. Agent Delegation (Fire-and-Forget)

When an AI Agent or specialized agent is connected to `input-tools`, the parent can delegate tasks:

```python
async def _execute_delegated_agent(args, config):
    # Inject API key for child agent
    provider = detect_ai_provider(node_type, child_params)
    api_key = await ai_service.auth.get_api_key(provider)
    child_params['api_key'] = api_key

    # Build prompt from delegation args
    child_params['prompt'] = f"{args['task']}\n\nContext:\n{args.get('context', '')}"

    # Spawn as background task
    async def run_child_agent():
        await broadcaster.update_node_status(node_id, "executing", {...})
        result = await handle_chat_agent(node_id, node_type, child_params, child_context, ...)
        await broadcaster.update_node_status(node_id, "success", {...})
        return result

    task = asyncio.create_task(run_child_agent())
    _delegated_tasks[task_id] = task

    # Return immediately -- parent continues without waiting
    return {"status": "delegated", "task_id": task_id}
```

Design decisions:
- **Memory isolation**: Child uses its own connected memory, not shared with parent
- **Error isolation**: Child errors don't propagate to parent
- **Task tracking**: Background tasks in `_delegated_tasks` dict, cleaned up on completion

---

## Memory Integration

### Collection

Memory data collected from `input-memory` handle in `_collect_agent_connections()`:

```python
if target_handle == 'input-memory':
    memory_params = await database.get_node_parameters(source_node_id)
    memory_data = {
        'node_id': source_node_id,
        'session_id': memory_params.get('sessionId', 'default'),
        'window_size': int(memory_params.get('windowSize', 10)),
        'memory_content': memory_params.get('memoryContent', ''),  # Markdown
        'long_term_enabled': memory_params.get('longTermEnabled', False),
        'retrieval_count': int(memory_params.get('retrievalCount', 3))
    }
```

### Message Construction

```python
# 1. System message (with skills already injected)
initial_messages = [SystemMessage(content=system_message)]

# 2. Long-term memory retrieval (if enabled)
if memory_data.get('long_term_enabled'):
    store = _get_memory_vector_store(session_id)  # InMemoryVectorStore per session
    docs = store.similarity_search(prompt, k=retrieval_count)
    initial_messages.append(SystemMessage(content=f"Relevant context:\n{docs}"))

# 3. Short-term conversation history
history_messages = _parse_memory_markdown(memory_content)  # Markdown -> [HumanMessage, AIMessage, ...]
initial_messages.extend(history_messages)

# 4. Current user prompt
initial_messages.append(HumanMessage(content=prompt))
```

### Post-Execution Save

After graph execution completes:

```python
# Append new exchange
updated = _append_to_memory_markdown(memory_content, 'human', prompt)
updated = _append_to_memory_markdown(updated, 'ai', response)

# Trim to window size, get removed texts
updated, removed = _trim_markdown_window(updated, window_size)

# Archive removed texts to vector store (if enabled)
if removed and long_term_enabled:
    store = _get_memory_vector_store(session_id)
    store.add_texts(removed)

# Save updated markdown back to node parameters
await database.save_node_parameters(memory_node_id, {'memoryContent': updated})
```

### Memory Format

Stored as human-readable markdown:

```markdown
# Conversation History

### **Human** (2025-01-30 14:23:45)
What is the weather like today?

### **Assistant** (2025-01-30 14:23:48)
I don't have access to real-time weather data...
```

---

## execute_agent vs execute_chat_agent

Both methods live in `server/services/ai.py` and follow the same general pattern. Key differences:

| Aspect | `execute_agent()` | `execute_chat_agent()` |
|--------|-------------------|----------------------|
| **Graph construction** | Always builds full LangGraph StateGraph | Conditional: LangGraph if tools, simple `ainvoke()` if no tools |
| **Tool failure** | Re-raises exceptions (LangGraph handles) | Returns `{"error": str(e)}` (softer handling) |
| **No-tool path** | N/A -- always uses graph | `response = await chat_model.ainvoke(messages)` (no graph overhead) |
| **Result metadata** | `agent_type: "agent"` | `agent_type: "chat" / "chat_with_skills" / "chat_with_tools" / "chat_with_skills_and_tools"` |

### Specialized Agent Routing

There are **15 specialized agents**. Most route to `handle_chat_agent`; `rlm_agent` and `claude_code_agent` have dedicated handlers:

```python
# server/services/node_executor.py
SPECIALIZED_AGENT_TYPES = {
    'android_agent', 'coding_agent', 'web_agent', 'task_agent', 'social_agent',
    'travel_agent', 'tool_agent', 'productivity_agent', 'payments_agent', 'consumer_agent',
    'autonomous_agent', 'orchestrator_agent', 'ai_employee',
    # rlm_agent and claude_code_agent are handled by dedicated handlers, not handle_chat_agent
}

# Most specialized agents map to handle_chat_agent
for agent_type in SPECIALIZED_AGENT_TYPES:
    registry[agent_type] = partial(handle_chat_agent, ai_service=self.ai_service, database=self.database)

# Dedicated handlers for agents that do not use LangGraph tool-calling
registry['rlm_agent'] = partial(handle_rlm_agent, ai_service=self.ai_service, database=self.database)
registry['claude_code_agent'] = partial(handle_claude_code_agent, ...)
```

### Temporal dispatch routing (post-F4)

Two settings flags route agent execution through different Temporal paths (see [TEMPORAL_ARCHITECTURE.md](TEMPORAL_ARCHITECTURE.md) for the full matrix):

| Flag | Off (default) | On |
|---|---|---|
| `TEMPORAL_PER_TYPE_DISPATCH` | Every node routes through the legacy `execute_node_activity` single dispatcher (WS round-trip to the FastAPI handler). | Each node routes through its per-type activity `node.{type}.v{version}` registered via `BaseNode.as_activity()`. Per-plugin retry / timeout / heartbeat configs apply. |
| `TEMPORAL_AGENT_WORKFLOW_ENABLED` | All 15 specialized + 2 base agents (`aiAgent` / `chatAgent`) run inside `execute_node_activity` (LangGraph loop in-activity). | The 15 migrating agent types become Temporal **child workflows** (`AgentWorkflow`). LLM steps + tool calls become activities; `agent.prepare_payload.v1` resolves the DB-backed payload as the workflow's first step. `deep_agent` / `rlm_agent` / `claude_code_agent` stay on the F4.A per-type activity path (externalised session state). |

Today both flags default to `false`; the wiring is shipped (F4.A at `8261b05`, F4.B infrastructure at `a4d009e`, per-agent dispatch at `0459131`) but production rollout awaits canary verification on a Temporal dev cluster.

**Team leads** (`orchestrator_agent`, `ai_employee`) use the same `handle_chat_agent` routing but add an `input-teammates` handle. Connected agents become `delegate_to_<type>` tools automatically via `_collect_teammate_connections()`. See [agent_teams.md](agent_teams.md).

### RLM Agent Pattern

`rlm_agent` replaces LangGraph tool-calling with a Python REPL executing LM calls recursively. Instead of paying one network round-trip per tool call, the RLM agent writes a code block that orchestrates many model invocations at once:

```python
# The LLM generates code like this, executed by RLMService
results = [llm_query(f"summarize: {url}") for url in urls]
best = rlm_query(f"pick the most relevant: {results}")
FINAL(best)
```

Exposed helpers inside the REPL:

| Helper | Purpose |
|---|---|
| `llm_query(prompt)` | Call the small model connected to `input-model` |
| `rlm_query(prompt)` | Recursively invoke the same RLM agent |
| `FINAL(answer)` | Signal completion and return the final answer |

Routing:

```python
# server/services/node_executor.py
registry['rlm_agent'] = partial(handle_rlm_agent, ai_service=self.ai_service, database=self.database)
```

`handle_rlm_agent` delegates to `RLMService` in `server/services/rlm_service.py`. See [rlm_service.md](rlm_service.md) for full details.

### Chat Agent Conditional Graph

```python
# In execute_chat_agent():
if all_tools:
    # Full LangGraph with tool execution loop
    agent_graph = build_agent_graph(chat_model, tools=all_tools, tool_executor=executor)
    final_state = await agent_graph.ainvoke(initial_state)
else:
    # Simple invoke -- no graph, no tool overhead
    response = await chat_model.ainvoke(messages)
```

This optimization means tool-less Chat Agent conversations skip LangGraph entirely for faster response times.
