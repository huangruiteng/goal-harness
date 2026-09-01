import { useState } from "react";
import { ArrowLeft, Check, Languages, Palette, Settings2 } from "lucide-react";

import type { WorkspaceLocale } from "./i18n";
import { useWorkspaceI18n } from "./i18n";
import { LarkSettingsPage } from "./lark-settings-page";
import type { WorkspaceGoal } from "./personal-workspace-model";

type WorkspaceSettingsTab = "lark" | "appearance" | "language";

const tabIcons: Record<WorkspaceSettingsTab, typeof Settings2> = {
  appearance: Palette,
  language: Languages,
  lark: Settings2,
};

export function WorkspaceSettingsPage({
  focusGoalConnection = false,
  goals,
  initialGoalId,
  initialTab = "lark",
  onChanged,
  onClose,
  onThemeChange,
  theme,
}: {
  focusGoalConnection?: boolean;
  goals: WorkspaceGoal[];
  initialGoalId?: string | null;
  initialTab?: WorkspaceSettingsTab;
  onChanged: () => void;
  onClose: () => void;
  onThemeChange: (theme: "brutal" | "paper") => void;
  theme: "brutal" | "paper";
}) {
  const { locale, setLocale, t } = useWorkspaceI18n();
  const [tab, setTab] = useState<WorkspaceSettingsTab>(initialTab);
  const tabs: Array<{ description: string; key: WorkspaceSettingsTab; label: string }> = [
    { description: t("settings.larkTabDescription"), key: "lark", label: "Lark" },
    { description: t("settings.appearanceTabDescription"), key: "appearance", label: t("settings.appearance") },
    { description: t("settings.languageTabDescription"), key: "language", label: t("settings.language") },
  ];
  const localeOptions: Array<{ description: string; label: string; value: WorkspaceLocale }> = [
    {
      description: t("settings.languageEnglishDescription"),
      label: t("settings.languageEnglish"),
      value: "en",
    },
    {
      description: t("settings.languageSimplifiedChineseDescription"),
      label: t("settings.languageSimplifiedChinese"),
      value: "zh-CN",
    },
  ];
  const headings: Record<WorkspaceSettingsTab, { description: string; eyebrow: string; title: string }> = {
    appearance: {
      description: t("settings.appearanceDescription"),
      eyebrow: t("settings.workspaceDisplay"),
      title: t("settings.appearance"),
    },
    language: {
      description: t("settings.languageDescription"),
      eyebrow: t("settings.workspaceDisplay"),
      title: t("settings.language"),
    },
    lark: {
      description: t("lark.description"),
      eyebrow: t("settings.goalConnections"),
      title: "Lark",
    },
  };
  const heading = headings[tab];

  return (
    <section aria-label={t("settings.title")} className="personal-settings-page" data-pw-theme={theme}>
      <aside className="personal-settings-sidebar">
        <button className="personal-settings-back" onClick={onClose} type="button">
          <ArrowLeft size={17} />
          <span>{t("settings.back")}</span>
        </button>
        <div className="personal-settings-title">
          <small>{t("settings.eyebrow")}</small>
          <strong>{t("settings.title")}</strong>
        </div>
        <nav aria-label={t("settings.categories")} className="personal-settings-tabs">
          {tabs.map((item) => {
            const Icon = tabIcons[item.key];
            return (
              <button aria-current={tab === item.key ? "page" : undefined} key={item.key} onClick={() => setTab(item.key)} type="button">
                <Icon size={17} />
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className="personal-settings-body">
        <header className="personal-settings-header">
          <div>
            <small>{heading.eyebrow}</small>
            <h1>{heading.title}</h1>
            <p>{heading.description}</p>
          </div>
        </header>
        {tab === "lark" ? (
          <LarkSettingsPage
            embedded
            focusGoalConnection={focusGoalConnection}
            goals={goals}
            initialGoalId={initialGoalId}
            onChanged={onChanged}
            onClose={onClose}
          />
        ) : null}

        {tab === "appearance" ? (
          <section className="personal-detail-card personal-appearance-settings">
            <small>{t("settings.workspaceDisplay")}</small>
            <h3>{t("settings.appearance")}</h3>
            <p>{t("settings.themeDescription")}</p>
            <div className="personal-settings-choice-group" role="radiogroup" aria-label={t("settings.workspaceTheme")}>
              <button aria-checked={theme === "paper"} onClick={() => onThemeChange("paper")} role="radio" type="button">
                <span className="personal-settings-theme-swatch is-paper" />
                <strong>{t("settings.themeDefault")}</strong>
                <small>{t("settings.themeDefaultDescription")}</small>
              </button>
              <button aria-checked={theme === "brutal"} onClick={() => onThemeChange("brutal")} role="radio" type="button">
                <span className="personal-settings-theme-swatch is-brutal" />
                <strong>{t("settings.themeHighContrast")}</strong>
                <small>{t("settings.themeHighContrastDescription")}</small>
              </button>
            </div>
          </section>
        ) : null}

        {tab === "language" ? (
          <section className="personal-settings-card">
            <header>
              <span className="personal-settings-icon"><Languages size={18} /></span>
              <div>
                <h2>{t("settings.language")}</h2>
                <p>{t("settings.languageDescription")}</p>
              </div>
            </header>
            <div aria-label={t("settings.language")} className="personal-language-options" role="radiogroup">
              {localeOptions.map((option) => (
                <button
                  aria-checked={locale === option.value}
                  className={locale === option.value ? "is-selected" : ""}
                  key={option.value}
                  onClick={() => setLocale(option.value)}
                  role="radio"
                  type="button"
                >
                  <span>
                    <strong>{option.label}</strong>
                    <small>{option.description}</small>
                  </span>
                  {locale === option.value ? <Check aria-hidden size={17} /> : null}
                </button>
              ))}
            </div>
            <footer>{t("settings.languageStoredLocally")}</footer>
          </section>
        ) : null}
      </main>
    </section>
  );
}
