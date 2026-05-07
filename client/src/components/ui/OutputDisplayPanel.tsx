import React, { useState } from 'react';
import Prism from 'prismjs';
import 'prismjs/components/prism-json';
import {
  Play,
  CheckCircle2,
  XCircle,
  ChevronRight,
  Trash2,
  Copy,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { ExecutionResult } from '../../services/executionService';
import { copyToClipboard, formatTimestamp } from '../../utils/formatters';

interface OutputDisplayPanelProps {
  results: ExecutionResult[];
  onClear?: () => void;
  selectedNode?: any;
  currentWorkflow?: any;
}

// ---------------------------------------------------------------------------
// Output transforms — render structured tool output as readable text.
// ---------------------------------------------------------------------------

const getExecutionData = (result: ExecutionResult) => {
  if (result.outputs) return result.outputs;
  if (result.data?.data) return result.data.data;
  return { message: 'No output data' };
};

const formatFilesystemOutput = (data: any): string | null => {
  const r = data?.result || data;
  if (!r) return null;

  if (r.content && r.file_path) {
    return `File: ${r.file_path}\n\n${r.content}`;
  }
  if (r.operation === 'write' && r.file_path) {
    return `Written: ${r.file_path}`;
  }
  if (r.operation === 'edit' && r.file_path) {
    return `Edited: ${r.file_path} (${r.occurrences || 1} replacement${(r.occurrences || 1) > 1 ? 's' : ''})`;
  }
  if (r.command !== undefined && r.stdout !== undefined) {
    const status = r.exit_code === 0 ? 'OK' : `Exit ${r.exit_code}`;
    const output = r.stdout || '(no output)';
    return `$ ${r.command}\n[${status}]\n\n${output}`;
  }
  if (r.entries && Array.isArray(r.entries)) {
    const lines = r.entries.map((e: any) =>
      `${e.type === 'dir' ? '[DIR]' : '     '} ${e.name}${e.size != null ? ` (${e.size} bytes)` : ''}`
    );
    return `${r.path || '.'} (${r.count || r.entries.length} items)\n\n${lines.join('\n')}`;
  }
  if (r.matches && Array.isArray(r.matches)) {
    if (r.matches.length === 0) return `No matches for "${r.pattern}"`;
    const lines = r.matches.slice(0, 50).map((m: any) =>
      m.line ? `${m.path}:${m.line}: ${m.text}` : (m.path || JSON.stringify(m))
    );
    const suffix = r.count > 50 ? `\n... and ${r.count - 50} more` : '';
    return `${r.count || r.matches.length} match${(r.count || r.matches.length) > 1 ? 'es' : ''} for "${r.pattern}"\n\n${lines.join('\n')}${suffix}`;
  }
  return null;
};

const formatTodoOutput = (data: any): string | null => {
  const r = data?.result || data;
  if (!r) return null;

  let todos: any[] = [];
  if (typeof r.todos === 'string') {
    try { todos = JSON.parse(r.todos); } catch { return null; }
  } else if (Array.isArray(r.todos)) {
    todos = r.todos;
  } else {
    return null;
  }

  if (todos.length === 0) return r.message || 'Todo list is empty.';

  const statusIcon: Record<string, string> = {
    pending: '[ ]',
    in_progress: '[~]',
    completed: '[x]',
  };
  const lines = todos.map((t: any, i: number) => {
    const icon = statusIcon[t.status] || '[ ]';
    return `${i + 1}. ${icon} ${t.content}`;
  });

  const counts = {
    pending: todos.filter((t: any) => t.status === 'pending').length,
    in_progress: todos.filter((t: any) => t.status === 'in_progress').length,
    completed: todos.filter((t: any) => t.status === 'completed').length,
  };
  const summary = `${todos.length} items: ${counts.completed} done, ${counts.in_progress} active, ${counts.pending} pending`;

  return `${summary}\n\n${lines.join('\n')}`;
};

const getMainResponse = (result: ExecutionResult): string | null => {
  const data = getExecutionData(result);

  const fsOutput = formatFilesystemOutput(data);
  if (fsOutput) return fsOutput;

  const todoOutput = formatTodoOutput(data);
  if (todoOutput) return todoOutput;

  if (data?.result?.response) return data.result.response;
  if (data?.response) return data.response;
  if (data?.result?.text) return data.result.text;
  if (data?.text) return data.text;
  if (data?.result?.content) return data.result.content;
  if (data?.content) return data.content;
  if (data?.result?.message) return data.result.message;
  if (data?.message && typeof data.message === 'string') return data.message;
  return null;
};

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

const OutputDisplayPanel: React.FC<OutputDisplayPanelProps> = ({ results, onClear }) => {
  const [expandedResults, setExpandedResults] = useState<Set<string>>(new Set());

  const toggleExpand = (key: string) => {
    setExpandedResults(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  if (results.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center bg-muted p-12 text-muted-foreground">
        <Play className="mb-4 h-12 w-12 stroke-1" />
        <div className="mb-1 text-base font-medium text-foreground">No executions yet</div>
        <div className="text-center text-sm text-muted-foreground">
          Run nodes to see their<br />execution results here
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col bg-muted">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border bg-background px-4 py-3">
        <div className="flex items-center gap-2">
          <Play className="h-4 w-4 text-success" />
          <span className="font-display text-sm font-semibold tracking-[var(--type-tracking-display)] text-fg-default [text-transform:var(--type-uppercase)]">Execution Results</span>
          <Badge variant="secondary" className="text-xs">{results.length}</Badge>
        </div>
        {onClear && (
          <Button variant="outline" size="sm" onClick={onClear}>
            <Trash2 className="h-3 w-3" />
            Clear
          </Button>
        )}
      </div>

      {/* Results List */}
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {results.map((result, index) => {
          const resultKey = `${result.nodeId}-${result.timestamp}-${index}`;
          const isExpanded = expandedResults.has(resultKey);
          const mainResponse = getMainResponse(result);
          const executionData = getExecutionData(result);

          return (
            <div
              key={resultKey}
              className={cn(
                'overflow-hidden rounded-md border bg-background',
                result.success ? 'border-success/40' : 'border-destructive/40'
              )}
            >
              {/* Result Header */}
              <div
                className={cn(
                  'flex items-center justify-between border-b px-3 py-2',
                  result.success
                    ? 'border-success/30 bg-success/10'
                    : 'border-destructive/30 bg-destructive/10'
                )}
              >
                <div className="flex items-center gap-2">
                  {result.success ? (
                    <CheckCircle2 className="h-4 w-4 text-success" />
                  ) : (
                    <XCircle className="h-4 w-4 text-destructive" />
                  )}
                  <span className="text-sm font-semibold text-foreground">
                    {result.nodeName}
                  </span>
                  <Badge variant={result.success ? 'success' : 'destructive'} className="text-xs">
                    {result.success ? 'SUCCESS' : 'FAILED'}
                  </Badge>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span>{result.executionTime.toFixed(2)}ms</span>
                  <span>{formatTimestamp(result.timestamp)}</span>
                </div>
              </div>

              {/* Error Display */}
              {result.error && (
                <div className="border-b border-destructive/30 bg-destructive/10 p-3">
                  <pre className="m-0 font-mono text-sm whitespace-pre-wrap break-words text-destructive">
                    {result.error}
                  </pre>
                </div>
              )}

              {/* Main Response (for AI / tool results) */}
              {mainResponse && (
                <div className="border-b border-border p-3">
                  <div className="mb-2 text-xs font-medium tracking-wider text-muted-foreground uppercase">
                    Response
                  </div>
                  <div className="text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground">
                    {mainResponse}
                  </div>
                </div>
              )}

              {/* JSON Output Toggle */}
              <div className="p-3">
                <div
                  onClick={() => toggleExpand(resultKey)}
                  className="flex cursor-pointer items-center justify-between rounded-sm bg-muted px-3 py-2 transition-colors hover:bg-card"
                >
                  <div className="flex items-center gap-2">
                    <ChevronRight
                      className={cn(
                        'h-3 w-3 text-muted-foreground transition-transform',
                        isExpanded && 'rotate-90'
                      )}
                    />
                    <span className="text-xs font-medium text-muted-foreground">
                      {isExpanded ? 'Hide' : 'Show'} Raw JSON
                    </span>
                  </div>
                  <Button
                    variant="outline"
                    size="xs"
                    onClick={(e) => {
                      e.stopPropagation();
                      copyToClipboard(executionData, 'JSON copied to clipboard!');
                    }}
                  >
                    <Copy className="h-3 w-3" />
                    Copy
                  </Button>
                </div>

                {/* Expanded JSON with prismjs highlighting via shared
                 *  .code-editor-container palette (see index.css). */}
                {isExpanded && (
                  <div className="code-editor-container mt-2 max-h-[300px] overflow-auto rounded-sm border border-border bg-muted p-3 font-mono text-xs text-foreground">
                    <code
                      dangerouslySetInnerHTML={{
                        __html: Prism.highlight(
                          JSON.stringify(executionData, null, 2),
                          Prism.languages.json,
                          'json',
                        ),
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer */}
      <div className="border-t border-border bg-background px-4 py-2 text-center text-xs text-muted-foreground">
        Results displayed in execution order
      </div>
    </div>
  );
};

export default OutputDisplayPanel;
