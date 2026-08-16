import { routeWorkspaceInput } from "../src/features/personal-workspace/personal-workspace-router.js";

function equal(actual: unknown, expected: unknown, label: string) {
  if (actual !== expected) throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`);
}

function ok(value: unknown, label: string) {
  if (!value) throw new Error(label);
}

const goalContext = {
  agents: [{ agentId: "codex", label: "Codex" }],
  goalId: "demo-goal",
  todos: [{ text: "整理验收材料", todoId: "todo-1" }],
};

equal(routeWorkspaceInput("我现在该做什么？只读回答，不要修改状态", { ...goalContext, goalId: null }).route, "projection", "manager projection");
equal(routeWorkspaceInput("不要设置 Heartbeat，只回答当前进度", goalContext).route, "agent_chat", "negated heartbeat");
equal(routeWorkspaceInput("每天推进这个 Goal，设置 heartbeat", goalContext).actionKind, "heartbeat.bind", "heartbeat outranks generic daily monitor");
equal(routeWorkspaceInput("创建一个 Todo：整理发布说明", goalContext).actionKind, "todo.create", "todo create");
equal(
  routeWorkspaceInput("做一次只读分析：判断刚刚新增的 Todo 是否与当前 Goal 一致。不要修改状态。", goalContext).route,
  "agent_chat",
  "existing todo read-only analysis",
);
equal(routeWorkspaceInput("把 todo-1 标记完成", goalContext).actionKind, "todo.update", "todo update");
equal(routeWorkspaceInput("帮我修复 MR 冲突，跑测试，然后 push", goalContext).actionKind, "todo.create", "execution task");
equal(routeWorkspaceInput("创建任务并设置 Heartbeat", goalContext).route, "clarify", "compound intent");
equal(routeWorkspaceInput("创建任务并设置 Heartbeat", goalContext).missingFields.join(","), "single_intent", "compound missing field");
equal(routeWorkspaceInput("现在部署到生产", goalContext).actionKind, "goal.update", "protected action");
equal(routeWorkspaceInput("解释一下现在的状态", goalContext).route, "agent_chat", "goal chat");

const createGoal = routeWorkspaceInput("创建 Goal：整理每周复盘", { ...goalContext, goalId: null });
equal(createGoal.route, "typed_action", "goal route");
equal(createGoal.actionKind, "goal.create", "goal action");
ok(createGoal.confidence >= 0.9, "goal confidence");

console.log("personal workspace router smoke passed");
