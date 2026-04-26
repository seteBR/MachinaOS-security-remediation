/**
 * Tests for useWorkflowOpsListener.
 *
 * Locks the runtime broadcast contract:
 *   - subscribes to `workflow_ops_apply` via the WS context
 *     addEventListener API
 *   - applies events scoped to the current workflow via applyOperations
 *   - other-workflow events trigger a sonner toast (no canvas mutation)
 *   - unsubscribes on unmount
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import type { Node, Edge } from 'reactflow';

import { useWorkflowOpsListener } from '../useWorkflowOpsListener';

// --- mocks (must come before importing modules that read them) ----------

const wsMock = {
  addEventListener: vi.fn<(type: string, handler: (data: any) => void) => () => void>(),
  saveNodeParameters: vi.fn().mockResolvedValue(true),
};

const storeMock = {
  currentWorkflowId: 'wf-current',
  loadWorkflow: vi.fn(),
};

vi.mock('../../contexts/WebSocketContext', () => ({
  useWebSocket: () => wsMock,
}));

vi.mock('../../store/useAppStore', () => ({
  useAppStore: (selector: any) => selector({
    currentWorkflow: { id: storeMock.currentWorkflowId },
    loadWorkflow: storeMock.loadWorkflow,
  }),
}));

const applyOpsMock = vi.fn().mockResolvedValue({ applied: 0, errors: [], refMap: {} });
vi.mock('../../lib/workflowOps', () => ({
  applyOperations: (...args: any[]) => applyOpsMock(...args),
}));

const toastMessageMock = vi.fn();
vi.mock('sonner', () => ({
  toast: { message: (...args: any[]) => toastMessageMock(...args) },
}));

// --- test scaffolding ---------------------------------------------------

function _ctx(overrides: Partial<{ nodes: Node[]; edges: Edge[] }> = {}) {
  return {
    nodes: overrides.nodes ?? [],
    edges: overrides.edges ?? [],
    setNodes: vi.fn(),
    setEdges: vi.fn(),
  };
}

let registeredHandler: ((data: any) => void) | null = null;
let unsubscribeMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  registeredHandler = null;
  unsubscribeMock = vi.fn();
  wsMock.addEventListener.mockImplementation((type, handler) => {
    if (type === 'workflow_ops_apply') registeredHandler = handler;
    return unsubscribeMock;
  });
  storeMock.currentWorkflowId = 'wf-current';
});

// ---------------------------------------------------------------------------

describe('useWorkflowOpsListener', () => {
  it('subscribes to workflow_ops_apply on mount', () => {
    renderHook(() => useWorkflowOpsListener(_ctx()));
    expect(wsMock.addEventListener).toHaveBeenCalledWith(
      'workflow_ops_apply',
      expect.any(Function),
    );
  });

  it('unsubscribes on unmount', () => {
    const { unmount } = renderHook(() => useWorkflowOpsListener(_ctx()));
    expect(unsubscribeMock).not.toHaveBeenCalled();
    unmount();
    expect(unsubscribeMock).toHaveBeenCalledTimes(1);
  });

  it('applies operations scoped to the current workflow', async () => {
    renderHook(() => useWorkflowOpsListener(_ctx()));
    expect(registeredHandler).not.toBeNull();

    const ops = [{ type: 'add_node', client_ref: 'n', node_type: 'x', parameters: {} }];
    await act(async () => {
      registeredHandler!({
        workflow_id: 'wf-current',
        caller_node_id: 'agent-1',
        operations: ops,
      });
    });

    expect(applyOpsMock).toHaveBeenCalledTimes(1);
    expect(applyOpsMock.mock.calls[0][0]).toEqual(ops);
    expect(toastMessageMock).not.toHaveBeenCalled();
  });

  it('toasts (not applies) when event targets a different workflow', () => {
    renderHook(() => useWorkflowOpsListener(_ctx()));
    expect(registeredHandler).not.toBeNull();

    act(() => {
      registeredHandler!({
        workflow_id: 'wf-other',
        caller_node_id: 'agent-1',
        operations: [{ type: 'add_node', client_ref: 'n', node_type: 'x', parameters: {} }],
      });
    });

    expect(applyOpsMock).not.toHaveBeenCalled();
    expect(toastMessageMock).toHaveBeenCalledTimes(1);
    const [title, opts] = toastMessageMock.mock.calls[0];
    expect(title).toMatch(/workflow created/i);
    expect(opts.action.label).toBe('Switch');
    // Switch handler triggers loadWorkflow with the foreign id.
    opts.action.onClick();
    expect(storeMock.loadWorkflow).toHaveBeenCalledWith('wf-other');
  });

  it('ignores empty-ops events that target the current workflow', async () => {
    renderHook(() => useWorkflowOpsListener(_ctx()));
    await act(async () => {
      registeredHandler!({ workflow_id: 'wf-current', operations: [] });
    });
    expect(applyOpsMock).not.toHaveBeenCalled();
    expect(toastMessageMock).not.toHaveBeenCalled();
  });
});
