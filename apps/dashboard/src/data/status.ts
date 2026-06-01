import rawStatus from "../../../../examples/status.example.json";
import { z } from "zod";

export const queueItemSchema = z.object({
  goal_id: z.string(),
  status: z.string(),
  waiting_on: z.string(),
  severity: z.string(),
  recommended_action: z.string(),
  source: z.string().optional(),
});

export const statusPayloadSchema = z.object({
  ok: z.boolean(),
  registry: z.string(),
  runtime_root: z.string(),
  goal_count: z.number(),
  run_count: z.number(),
  contract: z.object({
    ok: z.boolean(),
    summary: z.object({
      errors: z.number(),
      warnings: z.number(),
      checks: z.number(),
    }),
    errors: z.array(z.string()),
    warnings: z.array(z.string()),
  }),
  attention_queue: z.object({
    available: z.boolean(),
    item_count: z.number(),
    needs_user_or_controller: z.number(),
    needs_controller: z.number().optional().default(0),
    needs_codex: z.number(),
    watching_external_evidence: z.number(),
    items: z.array(queueItemSchema),
  }),
});

export type StatusPayload = z.infer<typeof statusPayloadSchema>;
export type QueueItem = z.infer<typeof queueItemSchema>;

export function parseStatusPayload(payload: unknown): StatusPayload {
  return statusPayloadSchema.parse(payload);
}

export function formatStatusError(error: unknown): string {
  if (error instanceof z.ZodError) {
    return error.issues.map((issue) => `${issue.path.join(".") || "root"}: ${issue.message}`).join("; ");
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

export const exampleStatusPayload = parseStatusPayload(rawStatus);
