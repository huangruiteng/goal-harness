import assert from "node:assert/strict";
import test from "node:test";

import {
  NEXT_ACTION_BINDING_SCHEMA,
  TODO_NEXT_ACTION_REQUEST_SCHEMA,
  transitionTodoNextAction,
  type TodoNextActionSnapshot,
} from "../../loopx/control_plane/todos/next_action.ts";

function todo(
  todoId: string,
  overrides: Partial<TodoNextActionSnapshot> = {},
): TodoNextActionSnapshot {
  return {
    todo_id: todoId,
    status: "open",
    task_class: "advancement_task",
    priority: "P1",
    text: `[P1] ${todoId}`,
    index: 1,
    completion_continuation: null,
    successor_todo_ids: [],
    ...overrides,
  };
}

test("completion orders open work by typed priority, not display text", () => {
  const completed = todo("todo_completed", {
    status: "done",
    text: "[P1] Complete the current work.",
    completion_continuation: "successor",
    successor_todo_ids: ["todo_typed_p1", "todo_typed_p2"],
  });
  const typedP1 = todo("todo_typed_p1", {
    priority: "P1",
    text: "[P4] Text intentionally disagrees with typed priority.",
    index: 3,
  });
  const typedP2 = todo("todo_typed_p2", {
    priority: "P2",
    text: "[P0] Text intentionally disagrees with typed priority.",
    index: 2,
  });
  const lines = [
    "## Next Action",
    "",
    `- ${completed.text}`,
    `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=${completed.todo_id} -->`,
    "",
  ];

  const result = transitionTodoNextAction(
    settleRequest(lines, [completed, typedP2, typedP1]),
  );

  assert.equal(result.outcome, "settled");
  assert.equal(result.next_todo_id, typedP1.todo_id);
  assert.equal(result.next_action, typedP1.text);
});

function settleRequest(
  lines: string[],
  todos: TodoNextActionSnapshot[],
  completedTodoId = "todo_completed",
  materializedTodoIds = todos.map((item) => item.todo_id),
): Record<string, unknown> {
  return {
    schema_version: TODO_NEXT_ACTION_REQUEST_SCHEMA,
    operation: "settle_completion",
    lines,
    todo_id: completedTodoId,
    agent_todos: todos,
    materialized_todo_ids: materializedTodoIds,
  };
}

test("generated Next Action binding is typed and input-immutable", () => {
  const lines = [
    "## Next Action",
    "",
    "- [P1] Validate the project connection.",
    "",
    "## Progress Ledger",
    "",
  ];
  const before = structuredClone(lines);

  const result = transitionTodoNextAction({
    schema_version: TODO_NEXT_ACTION_REQUEST_SCHEMA,
    operation: "bind",
    lines,
    todo_id: "TODO_Connection",
  });

  assert.equal(result.changed, true);
  assert.equal(result.matched, true);
  assert.equal(result.outcome, "bound");
  assert.equal(
    result.lines.includes(
      `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=todo_connection -->`,
    ),
    true,
  );
  assert.deepEqual(lines, before);
});

test("binding never overwrites an existing or malformed ownership directive", () => {
  const directives = [
    `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=todo_other -->`,
    "<!-- loopx:next-action schema=loopx_next_action_binding_v1 todo_id=todo_other -->",
    `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=invalid -->`,
  ];
  for (const directive of directives) {
    const lines = [
      "## Next Action",
      "",
      "- [P1] Validate the project connection.",
      directive,
      "",
    ];
    const result = transitionTodoNextAction({
      schema_version: TODO_NEXT_ACTION_REQUEST_SCHEMA,
      operation: "bind",
      lines,
      todo_id: "todo_connection",
    });

    assert.equal(result.changed, false);
    assert.deepEqual(result.lines, lines);
  }
});

test("completion settles from the final Todo snapshot and skips control work", () => {
  const completed = todo("todo_completed", {
    status: "done",
    text: "[P1] Validate the project connection.",
    completion_continuation: "successor",
    successor_todo_ids: ["todo_successor"],
  });
  const monitor = todo("todo_monitor", {
    text: "[P0] Poll an external dependency.",
    task_class: "continuous_monitor",
    index: 2,
  });
  const blocker = todo("todo_blocker", {
    text: "[P0] Wait for owner input.",
    task_class: "blocker",
    index: 3,
  });
  const successor = todo("todo_successor", {
    text: "[P2] Implement and validate the requested behavior.",
    index: 4,
  });
  const lines = [
    "## Next Action",
    "",
    `- ${completed.text}`,
    `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=${completed.todo_id} -->`,
    "",
    "## Progress Ledger",
    "",
  ];

  const result = transitionTodoNextAction(
    settleRequest(lines, [completed, monitor, blocker, successor]),
  );

  assert.equal(result.outcome, "settled");
  assert.equal(result.match_source, "typed_todo_binding");
  assert.equal(result.next_todo_id, successor.todo_id);
  assert.equal(result.next_action, successor.text);
  assert.deepEqual(result.lines.slice(0, 5), [
    "## Next Action",
    "",
    `- ${successor.text}`,
    `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=${successor.todo_id} -->`,
    "",
  ]);
});

test("successor completion fence waits until every declared successor exists", () => {
  const completed = todo("todo_completed", {
    status: "done",
    text: "[P1] Complete the bounded implementation.",
    completion_continuation: "successor",
    successor_todo_ids: ["todo_landed", "todo_not_landed"],
  });
  const landed = todo("todo_landed", { index: 2 });
  const lines = [
    "## Next Action",
    "",
    `- ${completed.text}`,
    `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=${completed.todo_id} -->`,
    "",
  ];

  const result = transitionTodoNextAction(
    settleRequest(lines, [completed, landed]),
  );

  assert.equal(result.outcome, "awaiting_successor");
  assert.equal(result.changed, false);
  assert.deepEqual(result.lines, lines);
});

test("legacy exact text is migrated once, including wrapped Markdown", () => {
  const completed = todo("todo_completed", {
    status: "done",
    text: "[P1] Validate the legacy project connection and record the result.",
    completion_continuation: "no_followup",
  });
  const lines = [
    "## Next Action",
    "",
    "- [P1] Validate the legacy project connection",
    "  and record the result.",
    "",
    "## Progress Ledger",
    "",
  ];

  const result = transitionTodoNextAction(settleRequest(lines, [completed]));

  assert.equal(result.outcome, "settled");
  assert.equal(result.match_source, "legacy_exact_text");
  assert.equal(result.next_todo_id, null);
  assert.deepEqual(result.lines.slice(0, 3), [
    "## Next Action",
    "",
    "## Progress Ledger",
  ]);
});

test("owner-authored, multiply-bound, and unknown-schema routes fail closed", () => {
  const completed = todo("todo_completed", {
    status: "done",
    text: "[P1] Validate the project connection.",
    completion_continuation: "no_followup",
  });
  const cases = [
    ["## Next Action", "", "- Keep the owner-approved route.", ""],
    [
      "## Next Action",
      "",
      `- ${completed.text}`,
      `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=${completed.todo_id} -->`,
      `<!-- loopx:next-action schema=${NEXT_ACTION_BINDING_SCHEMA} todo_id=todo_conflict -->`,
      "",
    ],
    [
      "## Next Action",
      "",
      `- ${completed.text}`,
      `<!-- loopx:next-action schema=loopx_next_action_binding_v1 todo_id=${completed.todo_id} -->`,
      "",
    ],
    [
      "## Next Action",
      "",
      `- ${completed.text}`,
      "<!-- loopx:next-action schema=loopx_next_action_binding_v0 todo_id=invalid -->",
      "",
    ],
  ];

  for (const lines of cases) {
    const result = transitionTodoNextAction(settleRequest(lines, [completed]));
    assert.equal(result.outcome, "route_unmatched");
    assert.equal(result.changed, false);
    assert.deepEqual(result.lines, lines);
  }
});

test("runtime decoder rejects malformed authority input before transition", () => {
  const { priority: _priority, ...snapshotWithoutPriority } = todo(
    "todo_completed",
    { status: "done" },
  );
  assert.throws(
    () =>
      transitionTodoNextAction({
        schema_version: TODO_NEXT_ACTION_REQUEST_SCHEMA,
        operation: "settle_completion",
        lines: ["## Next Action"],
        todo_id: "todo_completed",
        agent_todos: [snapshotWithoutPriority],
        materialized_todo_ids: ["todo_completed"],
      }),
    /priority must be a non-empty string/,
  );
  assert.throws(
    () =>
      transitionTodoNextAction({
        schema_version: TODO_NEXT_ACTION_REQUEST_SCHEMA,
        operation: "settle_completion",
        lines: ["## Next Action"],
        todo_id: "todo_completed",
        agent_todos: [
          {
            ...todo("todo_completed"),
            status: "completed",
          },
        ],
        materialized_todo_ids: ["todo_completed"],
      }),
    /status is unsupported/,
  );
  assert.throws(
    () =>
      transitionTodoNextAction({
        schema_version: "unsupported",
        operation: "bind",
        lines: ["## Next Action"],
        todo_id: "todo_completed",
      }),
    /request schema mismatch/,
  );
});
