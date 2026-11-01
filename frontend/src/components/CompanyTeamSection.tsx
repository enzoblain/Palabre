import type { CatalogLimits, MemberIn, Personality, PersonalityPreset, Role } from "../api";
import { useI18n } from "../i18n";
import { TeamEditor } from "./TeamEditor";

export type CreationMode = "auto" | "manual";

/** Company team: hired from a description (auto) or listed by hand (manual). */
export function CompanyTeamSection({
  creation, onCreationChange, description, onDescriptionChange, employeeCount, onEmployeeCountChange,
  custom, onCustomChange, roles, personality, presets, limits, names, claudeAccounts,
  presetsFailed, onRetryPresets, problems,
}: {
  creation: CreationMode;
  onCreationChange: (creation: CreationMode) => void;
  description: string;
  onDescriptionChange: (description: string) => void;
  employeeCount: number;
  onEmployeeCountChange: (count: number) => void;
  custom: MemberIn[] | null;
  onCustomChange: (members: MemberIn[]) => void;
  roles: Record<string, Role> | null;
  personality: Personality | null;
  presets: Record<string, PersonalityPreset> | null;
  limits: CatalogLimits | null;
  names: string[];
  claudeAccounts: number;
  presetsFailed: boolean;
  onRetryPresets: () => void;
  problems: string[];
}) {
  const { t } = useI18n();

  return (
    <section className="panel">
      <div className="team-head">
        <h2>{t("new.yourTeam")}</h2>
        <div className="segmented" role="tablist">
          <button type="button" role="tab" aria-selected={creation === "auto"} className={creation === "auto" ? "selected" : ""}
            onClick={() => onCreationChange("auto")}>{t("new.creationAuto")}</button>
          <button type="button" role="tab" aria-selected={creation === "manual"} className={creation === "manual" ? "selected" : ""}
            disabled={!roles || !personality || !presets || !limits} onClick={() => onCreationChange("manual")}>
            {t("new.creationManual")}
          </button>
        </div>
      </div>
      {presetsFailed && (
        <p className="error" role="alert">
          {t("new.presetsFailed")}{" "}
          <button type="button" onClick={onRetryPresets}>{t("new.presetsRetry")}</button>
        </p>
      )}
      {creation === "auto" ? (
        <>
          <p className="muted">{t("new.introAuto")}</p>
          <label>
            {t("new.description")}
            <textarea required rows={4} maxLength={10000} value={description}
              onChange={(e) => onDescriptionChange(e.target.value)} placeholder={t("new.descriptionPlaceholder")} />
          </label>
          <label className="narrow">
            {t("new.employeeCount")}
            <input type="number" min={limits?.min_team_size} max={limits?.max_agents} value={employeeCount}
              onChange={(e) => onEmployeeCountChange(Number(e.target.value))} />
          </label>
        </>
      ) : (
        <>
          {limits && <p className="muted">{t("new.introManual", { min: limits.min_team_size })}</p>}
          {custom && roles && personality && presets && limits && (
            <TeamEditor members={custom} onChange={onCustomChange} roles={roles} personality={personality} presets={presets}
              names={names} claudeAccounts={claudeAccounts} limits={limits} mandatoryRole={limits.mandatory_role} />
          )}
        </>
      )}
      {problems.map((problem) => <p key={problem} className="error" role="alert">{problem}</p>)}
    </section>
  );
}
