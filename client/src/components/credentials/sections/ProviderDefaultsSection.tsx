/**
 * ProviderDefaultsSection — provider default LLM parameters.
 *
 * shadcn Form composition (react-hook-form + zod). Watches `default_model`
 * to refetch model constraints, and toggles conditional thinking / reasoning
 * fields based on `thinking_enabled` + the constraint's thinking_type.
 */

import React, { useCallback, useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Loader2, Settings } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { useApiKeys, type ProviderDefaults, type ModelConstraints } from '../../../hooks/useApiKeys';
import { useWebSocket } from '../../../contexts/WebSocketContext';

const formSchema = z.object({
  default_model: z.string().optional().default(''),
  temperature: z.number().optional(),
  max_tokens: z.number().int().min(1).optional(),
  thinking_enabled: z.boolean().optional().default(false),
  thinking_budget: z.number().int().min(1024).max(16000).optional(),
  reasoning_effort: z.enum(['low', 'medium', 'high']).optional(),
  reasoning_format: z.enum(['parsed', 'hidden']).optional(),
});

type FormValues = z.infer<typeof formSchema>;

interface Props {
  providerId: string;
}

const ProviderDefaultsSection: React.FC<Props> = ({ providerId }) => {
  const { getProviderDefaults, saveProviderDefaults, getStoredModels, getModelConstraints, isConnected } = useApiKeys();
  // Subscribe to apiKeyStatuses[providerId]: WebSocketContext updates
  // this reactively after a successful validate (handler at line 2175-
  // 2180) AND on the backend's api_key_status broadcast (line 686-696
  // -- fired after the validator stores fresh models). Adding it as a
  // dep to the fetch effect below makes the model dropdown refresh
  // immediately after Fetch instead of requiring a page reload.
  const { apiKeyStatuses } = useWebSocket();
  const apiKeyStatus = apiKeyStatuses[providerId];

  const [models, setModels] = useState<string[]>([]);
  const [constraints, setConstraints] = useState<ModelConstraints | null>(null);
  const [loading, setLoading] = useState(false);

  const form = useForm({
    resolver: zodResolver(formSchema),
    defaultValues: {},
  });
  const selectedModel = form.watch('default_model');
  const thinkingEnabled = form.watch('thinking_enabled');
  const { isDirty } = form.formState;

  // Load defaults + models on mount AND on providerId change.
  // Reset models / constraints synchronously when the provider switches
  // so a stale list from the previous panel can't bleed through. Without
  // this, opening "OpenAI" then "LM Studio" left the OpenAI model list
  // visible in the LM Studio dropdown — the dropdown only saw an
  // explicit `setModels(m)` when the new fetch returned a non-empty
  // list, so an empty `lmstudio` response (no Fetch clicked yet) was a
  // no-op and the previous panel's state survived.
  useEffect(() => {
    if (!isConnected) return;
    setModels([]);
    setConstraints(null);
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [d, m] = await Promise.all([
          getProviderDefaults(providerId),
          getStoredModels(providerId),
        ]);
        if (!cancelled) {
          form.reset((d as Partial<ProviderDefaults>) ?? {});
          // Unconditional set: clears the dropdown when the fetch comes
          // back empty (e.g. local-LLM panel before "Fetch" was clicked,
          // or a freshly-removed key).
          setModels(m ?? []);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [providerId, isConnected, apiKeyStatus]);

  // Refetch constraints when selected model changes.
  useEffect(() => {
    if (!isConnected || !selectedModel) return;
    let cancelled = false;
    getModelConstraints(selectedModel, providerId).then((c) => {
      if (cancelled) return;
      setConstraints(c);
      if (c?.max_output_tokens && form.getValues('max_tokens') !== c.max_output_tokens) {
        form.setValue('max_tokens', c.max_output_tokens, { shouldDirty: false });
      }
    });
    return () => { cancelled = true; };
  }, [selectedModel, providerId, isConnected]);

  const onSubmit = useCallback(
    async (values: FormValues) => {
      setLoading(true);
      try {
        const ok = await saveProviderDefaults(providerId, values as ProviderDefaults);
        if (ok) form.reset(values);
      } finally {
        setLoading(false);
      }
    },
    [providerId, saveProviderDefaults, form],
  );

  const [tempMin, tempMax] = constraints?.temperature_range ?? [0, 2];
  const maxOut = constraints?.max_output_tokens;
  const thinkType = constraints?.thinking_type;
  const canThink = constraints?.supports_thinking;
  const fixedTemp = constraints?.is_reasoning_model && tempMin === tempMax;

  const numberOnChange =
    (field: { onChange: (v: number | undefined) => void }) =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value;
      field.onChange(raw === '' ? undefined : Number(raw));
    };

  return (
    <Accordion type="single" collapsible defaultValue="defaults">
      <AccordionItem value="defaults">
        <AccordionTrigger>
          <span className="flex items-center gap-2">
            <Settings className="h-4 w-4" /> Default Parameters
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <div className={loading ? 'pointer-events-none opacity-60' : ''}>
            <Form {...form}>
              <form
                id={`provider-defaults-form-${providerId}`}
                onSubmit={form.handleSubmit(onSubmit)}
                className="flex flex-col gap-3"
              >
                <FormField
                  control={form.control}
                  name="default_model"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Default Model</FormLabel>
                      <Select value={field.value ?? ''} onValueChange={field.onChange}>
                        <FormControl>
                          <SelectTrigger>
                            <SelectValue
                              placeholder={models.length ? 'Select model' : 'Validate API key first'}
                            />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {models.map((m) => (
                            <SelectItem key={m} value={m}>
                              {m}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormDescription>Model used when none specified</FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {constraints && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    {maxOut != null && (
                      <Badge variant="success">
                        Max Output: {maxOut.toLocaleString()}
                      </Badge>
                    )}
                    {constraints.context_length != null && (
                      <Badge variant="info">
                        Context: {constraints.context_length.toLocaleString()}
                      </Badge>
                    )}
                    <Badge variant="secondary">
                      Temp: {tempMin}-{tempMax}
                    </Badge>
                    {canThink && (
                      <Badge variant="warning">Thinking: {thinkType}</Badge>
                    )}
                    {constraints.is_reasoning_model && (
                      <Badge variant="outline">Reasoning</Badge>
                    )}
                  </div>
                )}

                {!fixedTemp && (
                  <FormField
                    control={form.control}
                    name="temperature"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Temperature</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min={tempMin}
                            max={tempMax}
                            step={0.1}
                            className="w-24"
                            value={field.value ?? ''}
                            onChange={numberOnChange(field)}
                          />
                        </FormControl>
                        <FormDescription>
                          Controls randomness ({tempMin}-{tempMax})
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                <FormField
                  control={form.control}
                  name="max_tokens"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Max Tokens</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={1}
                          max={maxOut || undefined}
                          className="w-32"
                          value={field.value ?? ''}
                          onChange={numberOnChange(field)}
                        />
                      </FormControl>
                      <FormDescription>
                        {maxOut != null ? `Up to ${maxOut.toLocaleString()}` : 'Maximum response length'}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {canThink && (
                  <FormField
                    control={form.control}
                    name="thinking_enabled"
                    render={({ field }) => (
                      <FormItem className="flex flex-row items-center justify-between rounded-md border border-border p-3">
                        <div className="space-y-0.5">
                          <FormLabel>Thinking / Reasoning</FormLabel>
                          <FormDescription>Extended thinking ({thinkType})</FormDescription>
                        </div>
                        <FormControl>
                          <Switch checked={!!field.value} onCheckedChange={field.onChange} />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                )}

                {canThink && thinkType === 'budget' && thinkingEnabled && (
                  <FormField
                    control={form.control}
                    name="thinking_budget"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Thinking Budget</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            min={1024}
                            max={16000}
                            className="w-28"
                            value={field.value ?? ''}
                            onChange={numberOnChange(field)}
                          />
                        </FormControl>
                        <FormDescription>Token budget (1024-16000)</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                {canThink && thinkType === 'effort' && thinkingEnabled && (
                  <FormField
                    control={form.control}
                    name="reasoning_effort"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Reasoning Effort</FormLabel>
                        <Select value={field.value ?? ''} onValueChange={field.onChange}>
                          <FormControl>
                            <SelectTrigger className="w-32">
                              <SelectValue placeholder="Select" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="low">Low</SelectItem>
                            <SelectItem value="medium">Medium</SelectItem>
                            <SelectItem value="high">High</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormDescription>Low, medium, or high</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                {canThink && thinkType === 'format' && thinkingEnabled && (
                  <FormField
                    control={form.control}
                    name="reasoning_format"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Reasoning Format</FormLabel>
                        <Select value={field.value ?? ''} onValueChange={field.onChange}>
                          <FormControl>
                            <SelectTrigger className="w-32">
                              <SelectValue placeholder="Select" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value="parsed">Parsed</SelectItem>
                            <SelectItem value="hidden">Hidden</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormDescription>Parsed or hidden</FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                <Button
                  type="submit"
                  disabled={!isDirty || loading}
                  variant={isDirty ? 'default' : 'outline'}
                  className="w-full"
                >
                  {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                  Save Defaults
                </Button>
              </form>
            </Form>
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  );
};

export default ProviderDefaultsSection;
