import {
  ArrowLeft,
  ExternalLink,
  FlaskConical,
  GitCompareArrows,
  ShieldCheck,
  TimerReset,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import benchmarkData from "../../../../benchmark/swe-marathon/data.json";
import caseInsights from "../../../../benchmark/swe-marathon/case_insights.json";
import copy from "./swe-marathon-copy.json";

type Language = "en" | "zh";
type Arm = (typeof benchmarkData.arms)[number];

const armOrder = ["plain", "goal", "ssh-goal", "codex-cli", "heartbeat"] as const;
const publicAnalysisUrl =
  "https://github.com/huangruiteng/loopx/pull/3887#issuecomment-5535839229";
const repositoryStudyUrl =
  "https://github.com/huangruiteng/loopx/tree/main/benchmark/swe-marathon";

const studyObservation = caseInsights.study_observations[0];
const behaviorMetrics = studyObservation.metrics;
const zstdHeartbeat = caseInsights.records.find(
  (record) => record.case_id === "zstd-decoder" && record.run_id.includes("heartbeat"),
);

const armLabels: Record<Language, Record<string, string>> = {
  en: {
    plain: "Plain Codex",
    goal: "Native Goal",
    "ssh-goal": "Codex App SSH Goal + LoopX",
    "codex-cli": "Codex CLI Goal profile + LoopX*",
    heartbeat: "LoopX Turn (external-scheduler automation)",
  },
  zh: {
    plain: "裸 Codex",
    goal: "原生 Goal",
    "ssh-goal": "Codex App SSH Goal + LoopX",
    "codex-cli": "Codex CLI Goal profile + LoopX*",
    heartbeat: "LoopX Turn（外部调度 Automation）",
  },
};


function updateLanguage(language: Language) {
  const url = new URL(window.location.href);
  if (language === "zh") url.searchParams.set("lang", "zh");
  else url.searchParams.delete("lang");
  window.history.replaceState({}, "", url);
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
}

function HorizonDiagram({ language }: Readonly<{ language: Language }>) {
  const c = copy[language];
  return (
    <figure className="bm-horizon" aria-labelledby="benchmark-horizon-caption">
      <div className="bm-horizon-track" aria-hidden="true">
        {c.horizonLabels.map((label, index) => (
          <div className="bm-horizon-stop" key={label}>
            <i style={{ "--stop": index } as CSSProperties} />
            <span>{label}</span>
          </div>
        ))}
        <div className="bm-horizon-window">
          <span>SWE-Marathon</span>
          <b>{language === "zh" ? "多小时 / repo 级" : "multi-hour / repository scale"}</b>
        </div>
      </div>
      <figcaption id="benchmark-horizon-caption">
        {language === "zh"
          ? "示意：任务 horizon 足以让可见完成与隐藏正确性分离。"
          : "Conceptual view: the task horizon separates visible completion from hidden correctness."}
      </figcaption>
    </figure>
  );
}

function BarChart({
  title,
  values,
  format,
}: Readonly<{
  title: string;
  values: Array<[string, number, boolean?]>;
  format: (value: number) => string;
}>) {
  const max = Math.max(...values.map(([, value]) => value));
  return (
    <figure className="bm-bar-chart" aria-label={title}>
      <figcaption>{title}</figcaption>
      <div className="bm-bars">
        {values.map(([label, value, accent]) => (
          <div className="bm-bar-row" key={label}>
            <span>{label}</span>
            <div className="bm-bar-track">
              <i
                className={accent ? "is-accent" : undefined}
                style={{ width: `${Math.max(2, (value / max) * 100)}%` }}
              />
            </div>
            <b>{format(value)}</b>
          </div>
        ))}
      </div>
    </figure>
  );
}

export function SweMarathonBrief() {
  const [language, setLanguage] = useState<Language>(() =>
    new URLSearchParams(window.location.search).get("lang") === "zh" ? "zh" : "en",
  );
  const c = copy[language];
  const basePath = import.meta.env.BASE_URL;

  useEffect(() => {
    document.title = language === "zh"
      ? "LoopX × SWE-Marathon：持续自我验证"
      : "LoopX × SWE-Marathon: Continued self-verification";
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  }, [language]);

  const summaries = useMemo(
    () =>
      armOrder.map((arm) => ({
        arm,
        ...benchmarkData.arm_summary[arm],
      })),
    [],
  );

  const setLocale = (next: Language) => {
    setLanguage(next);
    updateLanguage(next);
  };

  return (
    <div className="bm-page" id="top">
      <header className="bm-topbar">
        <a href={`${basePath}${language === "zh" ? "?lang=zh" : ""}`} className="bm-home-link">
          <ArrowLeft size={14} /> {c.back}
        </a>
        <span className="bm-edition">RESEARCH BRIEF / 01</span>
        <div className="bm-top-actions">
          <div className="bm-language" aria-label="Language">
            <button className={language === "en" ? "is-active" : ""} onClick={() => setLocale("en")} type="button">EN</button>
            <button className={language === "zh" ? "is-active" : ""} onClick={() => setLocale("zh")} type="button">中文</button>
          </div>
          <a href={repositoryStudyUrl} target="_blank" rel="noreferrer">
            {c.source} <ExternalLink size={13} />
          </a>
        </div>
      </header>

      <main>
        <section className="bm-hero bm-shell">
          <div className="bm-hero-copy">
            <p className="bm-eyebrow"><FlaskConical size={14} /> {c.meta}</p>
            <h1>
              {language === "zh" ? (
                <>
                  <span className="bm-title-desktop">LoopX 让 Agent 在说“完成”<br />之后继续验证。</span>
                  <span className="bm-title-mobile">说“完成”后，<br />继续验证。</span>
                </>
              ) : c.title}
            </h1>
            <p className="bm-deck">{c.deck}</p>
            <span className="bm-evidence-tag"><ShieldCheck size={14} /> {c.evidenceTag}</span>
          </div>
        </section>

        <section className="bm-section bm-shell bm-summary" id="summary">
          <div className="bm-section-lead bm-section-lead-wide">
            <p className="bm-kicker">{c.executiveEyebrow}</p>
            <h2>{c.executiveTitle}</h2>
            <p>{c.executiveBody}</p>
          </div>
          <div className="bm-table-wrap bm-score-table bm-executive-table">
            <table>
              <thead><tr>{c.executiveColumns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
              <tbody>
                {summaries.map((row) => {
                  const owner = c.armRows.find(([arm]) => arm === row.arm)?.[1];
                  let rowClassName: string | undefined;
                  if (row.arm === "heartbeat") rowClassName = "is-highlight";
                  else if (row.arm === "codex-cli") rowClassName = "is-caution";
                  return (
                    <tr key={row.arm} className={rowClassName}>
                      <th scope="row"><code>{row.arm}</code><span>{armLabels[language][row.arm]}</span></th>
                      <td>{owner}</td>
                      <td>{row.reward.toFixed(3)}</td>
                      <td><strong>{row.partial.toFixed(3)}</strong></td>
                      <td>${Math.round(row.cost)}</td>
                      <td>{row.cont_total}</td>
                      <td>{c.executiveReads[row.arm]}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="bm-runner-note"><strong>{language === "zh" ? "Runner 注释" : "Runner note"}</strong>{c.runnerNote}</p>
        </section>

        <section className="bm-section bm-shell" id="background">
          <div className="bm-section-lead">
            <p className="bm-kicker">{c.backgroundEyebrow}</p>
            <h2>{c.backgroundTitle}</h2>
            <p>{c.backgroundBody}</p>
          </div>
          <HorizonDiagram language={language} />
          <div className="bm-fact-grid">
            {c.benchmarkFacts.map(([value, label, note]) => (
              <article key={label}>
                <strong>{value}</strong>
                <span>{label}</span>
                <small>{note}</small>
              </article>
            ))}
          </div>
        </section>

        <section className="bm-section bm-shell" id="mechanism">
          <div className="bm-section-lead bm-section-lead-wide">
            <p className="bm-kicker">{c.mechanismEyebrow}</p>
            <h2>{c.mechanismTitle}</h2>
            <p>{c.mechanismBody}</p>
          </div>
          <div className="bm-chart-grid">
            <BarChart
              title={c.stepsChart}
              values={[
                [armLabels[language].goal, behaviorMetrics.agent_step_ratio_vs_plain_median.goal_native],
                [armLabels[language]["codex-cli"], behaviorMetrics.agent_step_ratio_vs_plain_median["codex-cli"]],
                [armLabels[language].heartbeat, behaviorMetrics.agent_step_ratio_vs_plain_median.heartbeat],
                [armLabels[language]["ssh-goal"], behaviorMetrics.agent_step_ratio_vs_plain_median["ssh-goal"], true],
              ]}
              format={(value) => `${value.toFixed(2)}×`}
            />
            <BarChart
              title={c.densityChart}
              values={[
                [armLabels[language].plain, behaviorMetrics.self_verification_density_per_step_median.plain],
                [armLabels[language].goal, behaviorMetrics.self_verification_density_per_step_median.goal_native],
                [armLabels[language].heartbeat, behaviorMetrics.self_verification_density_per_step_median.heartbeat],
                [armLabels[language]["ssh-goal"], behaviorMetrics.self_verification_density_per_step_median["ssh-goal"], true],
              ]}
              format={(value) => value.toFixed(3)}
            />
          </div>
          <div className="bm-chain" aria-label="Mechanism chain">
            {c.mechanismChain.map(([number, title, body]) => (
              <article key={number}><span>{number}</span><h3>{title}</h3><p>{body}</p></article>
            ))}
          </div>
          <div className="bm-insight-grid bm-insight-grid-compact">
            {c.insights.map(([title, body], index) => (
              <article key={title}><span>0{index + 1}</span><h3>{title}</h3><p>{body}</p></article>
            ))}
          </div>
          <blockquote>
            <p>“{c.quote}”</p>
            <cite><a href={publicAnalysisUrl} target="_blank" rel="noreferrer">{c.quoteBy} <ExternalLink size={12} /></a></cite>
          </blockquote>
        </section>

        <section className="bm-section bm-shell" id="zstd">
          <div className="bm-section-lead bm-section-lead-wide">
            <p className="bm-kicker">{c.caseEyebrow}</p>
            <h2>{c.caseTitle}</h2>
            <p>{c.caseBody}</p>
          </div>
          <div className="bm-timeline">
            {c.timeline.map(([step, title, action, outcome], index) => (
              <article key={step} className={index > 0 ? "is-loopx" : undefined}>
                <span>{step}</span><h3>{title}</h3><p>{action}</p><strong>{outcome}</strong>
              </article>
            ))}
          </div>
          <div className="bm-case-note"><TimerReset size={18} /><p>{c.trajectoryNote}</p></div>
          {zstdHeartbeat ? <span className="bm-data-attestation">{language === "zh" ? "来源：" : "Source: "}{zstdHeartbeat.schema_version} · {zstdHeartbeat.confidence} confidence</span> : null}
        </section>

        <section className="bm-section bm-shell bm-official" id="official-comparison">
          <div className="bm-section-lead bm-section-lead-wide">
            <p className="bm-kicker">{c.officialEyebrow}</p>
            <h2>{c.officialTitle}</h2>
            <p>{c.officialBody}</p>
          </div>
          <div className="bm-table-wrap bm-official-table">
            <table>
              <thead><tr>{c.officialColumns.map((column) => <th key={column}>{column}</th>)}</tr></thead>
              <tbody>
                {c.officialRows.map(([dimension, study, official, interpretation]) => (
                  <tr key={dimension}>
                    <th scope="row">{dimension}</th>
                    <td>{study}</td>
                    <td>{official}</td>
                    <td>{interpretation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="bm-official-note"><strong>{language === "zh" ? "阅读方式" : "How to read it"}</strong>{c.officialNote}</p>
        </section>

        <section className="bm-section bm-shell bm-boundary" id="boundary">
          <div>
            <p className="bm-kicker">{c.limitsEyebrow}</p>
            <h2>{c.limitsTitle}</h2>
            <ul>{c.limits.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
          <aside>
            <GitCompareArrows size={24} />
            <h3>{c.nextTitle}</h3>
            <p>{c.nextBody}</p>
          </aside>
        </section>

        <section className="bm-section bm-shell" id="sources">
          <div className="bm-section-lead bm-section-lead-wide">
            <p className="bm-kicker">{c.sourcesEyebrow}</p>
            <h2>{c.sourcesTitle}</h2>
          </div>
          <div className="bm-source-list">
            {c.sourceItems.map(([title, body, href], index) => (
              <a href={href} target="_blank" rel="noreferrer" key={title}>
                <span>0{index + 1}</span><div><strong>{title}</strong><p>{body}</p></div><ExternalLink size={15} />
              </a>
            ))}
          </div>
        </section>
      </main>

      <footer className="bm-footer bm-shell"><span>LoopX / Research Brief 01</span><p>{c.footer}</p><a href="#top">{language === "zh" ? "回到顶部" : "Back to top"}</a></footer>
    </div>
  );
}
