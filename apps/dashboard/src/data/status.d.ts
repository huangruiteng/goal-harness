import { z } from "zod";
export declare const queueItemSchema: z.ZodObject<{
    goal_id: z.ZodString;
    status: z.ZodString;
    waiting_on: z.ZodString;
    severity: z.ZodString;
    recommended_action: z.ZodString;
    source: z.ZodOptional<z.ZodString>;
}, z.core.$strip>;
export declare const statusPayloadSchema: z.ZodObject<{
    ok: z.ZodBoolean;
    registry: z.ZodString;
    runtime_root: z.ZodString;
    goal_count: z.ZodNumber;
    run_count: z.ZodNumber;
    contract: z.ZodObject<{
        ok: z.ZodBoolean;
        summary: z.ZodObject<{
            errors: z.ZodNumber;
            warnings: z.ZodNumber;
            checks: z.ZodNumber;
        }, z.core.$strip>;
        errors: z.ZodArray<z.ZodString>;
        warnings: z.ZodArray<z.ZodString>;
    }, z.core.$strip>;
    attention_queue: z.ZodObject<{
        available: z.ZodBoolean;
        item_count: z.ZodNumber;
        needs_user_or_controller: z.ZodNumber;
        needs_controller: z.ZodDefault<z.ZodOptional<z.ZodNumber>>;
        needs_codex: z.ZodNumber;
        watching_external_evidence: z.ZodNumber;
        items: z.ZodArray<z.ZodObject<{
            goal_id: z.ZodString;
            status: z.ZodString;
            waiting_on: z.ZodString;
            severity: z.ZodString;
            recommended_action: z.ZodString;
            source: z.ZodOptional<z.ZodString>;
        }, z.core.$strip>>;
    }, z.core.$strip>;
}, z.core.$strip>;
export type StatusPayload = z.infer<typeof statusPayloadSchema>;
export type QueueItem = z.infer<typeof queueItemSchema>;
export declare const statusPayload: {
    ok: boolean;
    registry: string;
    runtime_root: string;
    goal_count: number;
    run_count: number;
    contract: {
        ok: boolean;
        summary: {
            errors: number;
            warnings: number;
            checks: number;
        };
        errors: string[];
        warnings: string[];
    };
    attention_queue: {
        available: boolean;
        item_count: number;
        needs_user_or_controller: number;
        needs_controller: number;
        needs_codex: number;
        watching_external_evidence: number;
        items: {
            goal_id: string;
            status: string;
            waiting_on: string;
            severity: string;
            recommended_action: string;
            source?: string | undefined;
        }[];
    };
};
