import { useEffect, useState } from "react";
import { Bell, Check, Loader2, X } from "lucide-react";

import type {
  PersonalWorkspaceCallbacks,
  WorkspaceGoal,
  WorkspaceGoalNotification,
} from "./personal-workspace-model";

type NotificationTarget = { enabled: boolean; provider: string; target_name: string };

type BindState =
  | { phase: "idle" }
  | { phase: "confirm"; target: string }
  | { phase: "busy" }
  | { phase: "error"; message: string };

function GoalNotificationRow({
  callbacks,
  goal,
  notification,
  targets,
  onChanged,
}: {
  callbacks: PersonalWorkspaceCallbacks;
  goal: WorkspaceGoal;
  notification?: WorkspaceGoalNotification;
  targets: NotificationTarget[];
  onChanged: () => void;
}) {
  const [bindState, setBindState] = useState<BindState>({ phase: "idle" });
  const [selectedTarget, setSelectedTarget] = useState(targets[0]?.target_name ?? "");
  const [toggleBusy, setToggleBusy] = useState(false);
  const [toggleError, setToggleError] = useState<string | null>(null);

  async function bind(execute: boolean) {
    if (!callbacks.onSetupGoalChannel || !selectedTarget) return;
    setBindState({ phase: "busy" });
    try {
      const result = await callbacks.onSetupGoalChannel({
        execute,
        goalId: goal.goalId,
        target: selectedTarget,
      });
      if (!result.ok) {
        setBindState({ phase: "error", message: result.public_summary ?? result.blocker ?? "绑定失败" });
        return;
      }
      if (!execute) {
        setBindState({ phase: "confirm", target: selectedTarget });
        return;
      }
      setBindState({ phase: "idle" });
      onChanged();
    } catch (error) {
      setBindState({ phase: "error", message: error instanceof Error ? error.message : "绑定失败" });
    }
  }

  async function toggleAutoNotify(autoNotify: boolean) {
    if (!callbacks.onToggleGoalAutoNotify) return;
    setToggleBusy(true);
    setToggleError(null);
    try {
      const result = await callbacks.onToggleGoalAutoNotify({ autoNotify, goalId: goal.goalId });
      if (!result.ok) {
        setToggleError(result.public_summary ?? result.blocker ?? "设置失败");
        return;
      }
      onChanged();
    } catch (error) {
      setToggleError(error instanceof Error ? error.message : "设置失败");
    } finally {
      setToggleBusy(false);
    }
  }

  const configured = notification?.configured === true;

  return (
    <li className="personal-notification-row">
      <div className="personal-notification-row-head">
        <strong>{goal.title}</strong>
        <span className={`personal-notification-badge ${configured ? "is-on" : "is-off"}`}>
          {configured ? (notification?.enabled ? "已绑定" : "已停用") : "未绑定"}
        </span>
      </div>
      {configured ? (
        <>
          <div className="personal-notification-meta">
            {notification?.targetRef ? <span>通知群：{notification.targetRef}</span> : null}
            <span>已发送 {notification?.receiptCount ?? 0} 条</span>
            {notification?.lastNotifiedAt ? <span>最近 {notification.lastNotifiedAt}</span> : null}
          </div>
          <label className="personal-notification-toggle">
            <input
              checked={notification?.humanGateAutoNotifyEnabled ?? false}
              disabled={toggleBusy}
              onChange={(event) => void toggleAutoNotify(event.target.checked)}
              type="checkbox"
            />
            <span>需要你确认时自动推送到群里</span>
            {toggleBusy ? <Loader2 aria-hidden className="is-spinning" size={14} /> : null}
          </label>
          {toggleError ? <p className="personal-notification-error">{toggleError}</p> : null}
        </>
      ) : targets.length === 0 ? (
        <p className="personal-notification-hint">
          还没有可用的通知群。通知群涉及机器人私有身份，请先在终端配置一次：
          <code>loopx goal-channel target add</code>
        </p>
      ) : bindState.phase === "confirm" ? (
        <div className="personal-notification-confirm">
          <p>将把「{goal.title}」绑定到通知群「{bindState.target}」，绑定时会验证机器人在群内并发送一条确认消息。</p>
          <div className="personal-notification-actions">
            <button className="personal-primary-action" onClick={() => void bind(true)} type="button">
              <Check size={15} />确认绑定
            </button>
            <button className="personal-secondary-action" onClick={() => setBindState({ phase: "idle" })} type="button">
              <X size={15} />取消
            </button>
          </div>
        </div>
      ) : (
        <div className="personal-notification-bind">
          <select
            aria-label={`为 ${goal.title} 选择通知群`}
            onChange={(event) => setSelectedTarget(event.target.value)}
            value={selectedTarget}
          >
            {targets.map((target) => (
              <option key={target.target_name} value={target.target_name}>{target.target_name}</option>
            ))}
          </select>
          <button
            className="personal-secondary-action"
            disabled={!selectedTarget || bindState.phase === "busy"}
            onClick={() => void bind(false)}
            type="button"
          >
            {bindState.phase === "busy" ? <Loader2 aria-hidden className="is-spinning" size={15} /> : <Bell size={15} />}
            绑定到通知群
          </button>
        </div>
      )}
      {bindState.phase === "error" ? <p className="personal-notification-error">{bindState.message}</p> : null}
    </li>
  );
}

export function NotificationSettingsPanel({
  callbacks,
  goalNotifications,
  goals,
  onChanged,
}: {
  callbacks: PersonalWorkspaceCallbacks;
  goalNotifications: WorkspaceGoalNotification[];
  goals: WorkspaceGoal[];
  onChanged: () => void;
}) {
  const [targets, setTargets] = useState<NotificationTarget[] | null>(null);
  const [targetsError, setTargetsError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!callbacks.onFetchNotificationTargets) {
      setTargets([]);
      return;
    }
    callbacks.onFetchNotificationTargets()
      .then((items) => { if (!cancelled) setTargets(items); })
      .catch((error: unknown) => {
        if (!cancelled) {
          setTargets([]);
          setTargetsError(error instanceof Error ? error.message : "通知群列表加载失败");
        }
      });
    return () => { cancelled = true; };
  }, [callbacks]);

  return (
    <section className="personal-detail-card personal-notification-settings">
      <small>飞书群通知</small>
      <h3>Goal 通知绑定</h3>
      <p>把 Goal 里需要你确认的变更推送到飞书群。绑定和开关在这里完成，推送逻辑沿用现有通道。</p>
      {targetsError ? <p className="personal-notification-error">{targetsError}</p> : null}
      <ul className="personal-notification-list">
        {goals.map((goal) => (
          <GoalNotificationRow
            callbacks={callbacks}
            goal={goal}
            key={goal.goalId}
            notification={goalNotifications.find((row) => row.goalId === goal.goalId)}
            onChanged={onChanged}
            targets={targets ?? []}
          />
        ))}
      </ul>
    </section>
  );
}
