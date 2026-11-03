import { useState } from "react";
import type { CatalogLimits, MemberIn, PersonalityPreset, Role } from "../api";
import { useI18n, translate } from "../i18n";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";
import { ShuffleIcon } from "./Icons";
import { JobPicker } from "./JobPicker";
import { PersonalityPicker } from "./PersonalityPicker";
import { type TeamProblem, teamWarningThreshold } from "../jobs";

function pick<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)];
}

/** A blank agent, filled in by the boss: no name, no role, and a personality the server draws. */
export function newMember(): MemberIn {
  return { name: "", roles: [], model: null, account: null, personality: null };
}

/** A first name from the catalog nobody in the team has yet. */
export function freeName(names: string[], taken: string[]): string {
  const free = names.filter((n) => !taken.some((t) => t.toLowerCase() === n.toLowerCase()));
  return free.length ? pick(free) : "";
}

/** The messages of the problems that keep the team from being created. */
export function problemMessages(problems: TeamProblem[], minSize: number, maxSize: number): string[] {
  const messages: Record<TeamProblem, () => string> = {
    none: () => translate("editor.problemNone"),
    tooSmall: () => translate("editor.problemTooSmall", { min: minSize }),
    tooBig: () => translate("editor.problemTooBig", { max: maxSize }),
    noLead: () => translate("editor.problemLead"),
    duplicate: () => translate("editor.problemDuplicate"),
    noName: () => translate("editor.problemNoName"),
    badName: () => translate("editor.problemBadName"),
    noRole: () => translate("editor.problemNoRole"),
  };
  return problems.map((problem) => messages[problem]());
}

/** The member every company starts with: the lead, with a drawn name. */
export function mandatoryMember(names: string[], role: string): MemberIn {
  return { ...newMember(), name: freeName(names, []), roles: [role] };
}

export function TeamEditor({ members, onChange, roles, presets, names, claudeAccounts, limits, mandatoryRole }: {
  members: MemberIn[];
  onChange: (members: MemberIn[]) => void;
  roles: Record<string, Role>;
  presets: Record<string, PersonalityPreset>;
  names: string[];
  claudeAccounts: number;
  limits: CatalogLimits;
  // Role of the first member, who cannot be removed and keeps this role: only their personality changes.
  // The lead must stay first: the editor never reorders members and `resize` only trims or appends.
  mandatoryRole?: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState<number | null>(null);
  const effective = spreadAccounts(members.map((m) => m.account), claudeAccounts);

  const update = (i: number, changes: Partial<MemberIn>) =>
    onChange(members.map((m, j) => (j === i ? { ...m, ...changes } : m)));

  function resize(count: number) {
    const n = Math.max(mandatoryRole ? 1 : 0, Math.min(limits.max_agents, count || 0));
    if (n <= members.length) return onChange(members.slice(0, n));
    const added = [...members];
    while (added.length < n) added.push(newMember());
    onChange(added);
    setOpen(members.length); // Open the first new agent to fill it in
  }

  const atLimit = members.length >= limits.max_agents;
  const nearLimit = members.length >= teamWarningThreshold(limits.max_agents);

  return (
    <div className="team-editor">
      <label className="narrow">
        {t("editor.count")}
        <input type="number" min={0} max={limits.max_agents} value={members.length}
          onChange={(e) => resize(Number(e.target.value))} />
      </label>

      <p role="status" className={nearLimit ? "team-count warning" : "team-count muted"}>
        {nearLimit && <span aria-hidden="true">⚠ </span>}
        {t("editor.teamCount", { count: members.length, max: limits.max_agents })}
        {nearLimit && ` ${t(atLimit ? "editor.limitReached" : "editor.limitClose")}`}
      </p>

      {members.length === 0 && <p className="muted">{t("editor.empty")}</p>}
      <ul className="editor-list">
        {members.map((m, i) => {
          const locked = !!mandatoryRole && i === 0;
          return (
          <li key={i} className="editor-card">
            <div className="editor-head">
              <Avatar name={m.name || "?"} size={32} />
              <input className="editor-name" value={m.name} disabled={locked} maxLength={40} aria-label={t("editor.nameAria")} placeholder={t("editor.namePlaceholder")}
                onChange={(e) => update(i, { name: e.target.value.replace(/\s/g, "") })} />
              {!locked && <button type="button" className="icon-btn" title={t("editor.pickName")}
                onClick={() => update(i, { name: freeName(names, members.map((x) => x.name)) })}>
                <ShuffleIcon size={14} />
              </button>}
              <span className="muted truncate editor-summary">
                {m.roles.map((r) => roles[r]?.title ?? r).join(" + ") || t("editor.noRole")}
              </span>
              <button type="button" className="btn btn-small" onClick={() => setOpen(open === i ? null : i)}>
                {open === i ? t("common.close") : t("common.edit")}
              </button>
              {locked ? (
                <span className="badge">{t("editor.mandatory")}</span>
              ) : (
                <button type="button" className="btn btn-small"
                  onClick={() => {
                    onChange(members.filter((_, j) => j !== i));
                    setOpen(null);
                  }}>{t("common.remove")}</button>
              )}
            </div>

            {open === i && (
              <div className="editor-details">
                {!locked && <JobPicker roles={roles} selected={m.roles}
                  onChange={(selected) => update(i, { roles: selected })} />}
                <PersonalityPicker presets={presets} selected={m.personality}
                  onSelect={(personality) => update(i, { personality })} />
                <div className="row">
                  {!locked && <label>
                    {t("editor.model")}
                    <select value={m.model ?? ""} onChange={(e) => update(i, { model: e.target.value || null })}>
                      <option value="">{t("editor.modelAuto")}</option>
                      {limits.models.map((model) => <option key={model} value={model}>{model}</option>)}
                    </select>
                  </label>}
                  {claudeAccounts > 1 && !locked && (
                    <label>
                      {t("editor.account")}
                      <AccountSelect value={m.account} effective={effective[i]} count={claudeAccounts}
                        onChange={(account) => update(i, { account })} />
                    </label>
                  )}
                </div>
              </div>
            )}
          </li>
          );
        })}
      </ul>

      <button type="button" className="btn btn-small" disabled={atLimit}
        aria-describedby={atLimit ? "team-limit-help" : undefined}
        onClick={() => resize(members.length + 1)}>{t("editor.addAgent")}</button>
      {atLimit && <p id="team-limit-help" className="muted">{t("editor.limitHelp", { max: limits.max_agents })}</p>}
    </div>
  );
}
