import { Node, Edge } from 'reactflow';

export const generateWorkflowId = (): string => 
  `workflow-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;

export const sanitizeNodesForComparison = (nodes: Node[]): Node[] =>
  nodes.map(n => ({ ...n, selected: undefined, dragging: undefined }));

export const sanitizeEdgesForComparison = (edges: Edge[]): Edge[] =>
  edges.map(e => ({ ...e, selected: undefined }));

export const serializeDateFields = <T extends { createdAt: Date; lastModified: Date }>(obj: T) => ({
  ...obj,
  createdAt: obj.createdAt.toISOString(),
  lastModified: obj.lastModified.toISOString(),
});

export const deserializeDateFields = <T extends { createdAt: string; lastModified: string }>(obj: T) => ({
  ...obj,
  createdAt: new Date(obj.createdAt),
  lastModified: new Date(obj.lastModified),
});

export const snapToGrid = (position: { x: number; y: number }, gridSize = 20) => ({
  x: Math.round(position.x / gridSize) * gridSize,
  y: Math.round(position.y / gridSize) * gridSize,
});

export const getDefaultNodePosition = (nodeCount: number): { x: number; y: number } =>
  nodeCount === 0 ? { x: 100, y: 200 } : { x: 0, y: 0 };

// Node-id remap on import lives backend-side in
// ``server/services/workflow_import.py::remap_node_ids`` — the import
// path is now backend-authoritative (``import_workflow`` WS handler),
// so there's no need for a duplicate frontend implementation. The
// in-canvas copy/paste path uses its own id scheme in ``useCopyPaste``.