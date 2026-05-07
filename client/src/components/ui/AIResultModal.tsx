import React from 'react';
import { Copy } from 'lucide-react';
import Modal from './Modal';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { copyToClipboard, formatTimestamp } from '../../utils/formatters';

interface AIResultModalProps {
  isOpen: boolean;
  onClose: () => void;
  result: {
    response: string;
    usage?: {
      promptTokens: number;
      completionTokens: number;
      totalTokens: number;
    };
    model: string;
    finishReason?: string;
    nodeId: string;
    nodeName: string;
    timestamp: string;
  } | null;
}

interface UsageStatProps {
  value: number;
  label: string;
}

const UsageStat: React.FC<UsageStatProps> = ({ value, label }) => (
  <Card className="p-2 text-center">
    <div className="text-base font-semibold text-foreground">{value}</div>
    <div className="text-xs text-muted-foreground">{label}</div>
  </Card>
);

const AIResultModal: React.FC<AIResultModalProps> = ({ isOpen, onClose, result }) => {
  if (!result) return null;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="AI Execution Result"
      maxWidth="800px"
      maxHeight="90vh"
    >
      <div className="flex h-full flex-col">
        {/* Header Info */}
        <div className="border-b border-border bg-muted p-4">
          <div className="mb-2 flex items-start justify-between">
            <div>
              <h3 className="m-0 font-display text-base font-semibold tracking-[var(--type-tracking-display)] text-fg-default [text-transform:var(--type-uppercase)]">
                {result.nodeName} Result
              </h3>
              <p className="mt-1 mb-0 text-sm text-muted-foreground">
                Model: {result.model} | {formatTimestamp(result.timestamp)}
              </p>
            </div>
            <Button
              size="sm"
              onClick={() => copyToClipboard(result.response, 'Response copied to clipboard!')}
            >
              <Copy className="h-3.5 w-3.5" />
              Copy Response
            </Button>
          </div>

          {/* Usage Stats */}
          {result.usage && (
            <div className="mt-2 grid grid-cols-[repeat(auto-fit,minmax(120px,1fr))] gap-2">
              <UsageStat value={result.usage.promptTokens} label="Prompt Tokens" />
              <UsageStat value={result.usage.completionTokens} label="Completion Tokens" />
              <UsageStat value={result.usage.totalTokens} label="Total Tokens" />
            </div>
          )}
        </div>

        {/* Response Content */}
        <div className="flex-1 overflow-y-auto p-4">
          <h4 className="m-0 mb-3 text-base font-medium text-foreground">Response:</h4>
          <div className="max-h-[400px] overflow-y-auto rounded-md border border-border bg-muted p-4 font-sans text-base leading-relaxed whitespace-pre-wrap text-foreground">
            {result.response}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border bg-muted p-4">
          <div className="text-xs text-muted-foreground">
            {result.finishReason && `Finish reason: ${result.finishReason}`}
          </div>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </Modal>
  );
};

export default AIResultModal;
