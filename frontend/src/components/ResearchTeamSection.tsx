import { type CatalogLimits, type MemberIn, type Mode, type Personality, type PersonalityPreset, type Role, type TeamMember, type TeamPreview } from "../api";
import { useI18n } from "../i18n";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";
import { ShuffleIcon } from "./Icons";
import { TeamEditor } from "./TeamEditor";

function teamSize(mode: Mode): number {
  return mode.seats.reduce((n, seat) => n + (seat.count ?? 1), 0);
}

/** The strongest opinions of an employee, e.g. ["bold", "quality"]. */
function traitChips(member: TeamMember, personality: Personality | null): { text: string; strong: boolean }[] {
  if (!personality) return [];
  return personality.axes
    .map((axis) => ({ axis, level: member.traits[axis.key] ?? 0 }))
    .filter(({ level }) => level !== 0)
    .sort((a, b) => Math.abs(b.level) - Math.abs(a.level))
    .slice(0, 3)
    .map(({ axis, level }) => ({
      text: (level > 0 ? axis.high : axis.low).split(" — ")[0],
      strong: Math.abs(level) === 2,
    }));
}

/** Research team: drawn at random from a mode, or built by hand. */
export function ResearchTeamSection({
  modes, mode, onModeChange, team, onDrawAnother, accounts, onAccountsChange, rapporteur, onRapporteurChange,
  custom, onCustomChange, onBuildByHand, roles, personality, presets, limits, names, claudeAccounts,
  presetsFailed, onRetryPresets, problems,
}: {
  modes: Record<string, Mode> | null;
  mode: string;
  onModeChange: (mode: string) => void;
  team: TeamPreview | null;
  onDrawAnother: () => void;
  accounts: Record<string, number>;
  onAccountsChange: (accounts: Record<string, number>) => void;
  rapporteur: string | null;
  onRapporteurChange: (rapporteur: string | null) => void;
  custom: MemberIn[] | null;
  onCustomChange: (members: MemberIn[] | null) => void;
  onBuildByHand: () => void;
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
  const effective = team ? spreadAccounts(team.employees.map((m) => accounts[m.name]), claudeAccounts) : [];

  return (
    <section className="panel">
      <div className="team-head">
        <h2>{t("new.yourTeam")}</h2>
        <div className="segmented" role="tablist">
          <button type="button" role="tab" aria-selected={!custom} className={!custom ? "selected" : ""}
            onClick={() => onCustomChange(null)}>{t("new.random")}</button>
          <button type="button" role="tab" aria-selected={!!custom} className={custom ? "selected" : ""}
            disabled={!roles || !personality || !presets || !limits} onClick={onBuildByHand}>{t("new.buildOwn")}</button>
        </div>
      </div>
      {presetsFailed && (
        <p className="error" role="alert">
          {t("new.presetsFailed")}{" "}
          <button type="button" onClick={onRetryPresets}>{t("new.presetsRetry")}</button>
        </p>
      )}
      <p className="muted">{custom ? t("new.introResearchCustom") : t("new.introResearch")}</p>
      <div className="modes">
        {modes && modes[mode] &&
          Object.entries(modes).map(([key, m]) => (
            <button type="button" key={key} className={`mode${key === mode ? " selected" : ""}`}
              onClick={() => onModeChange(key)}>
              <strong>{m.label}</strong>
              {!custom && <span className="mode-size">{t("new.people", { count: teamSize(m) })}</span>}
              <span className="mode-rule">{m.rules[0]}</span>
            </button>
          ))}
      </div>

      {custom && roles && personality && presets && limits ? (
        <TeamEditor members={custom} onChange={onCustomChange} roles={roles} personality={personality} presets={presets}
          names={names} claudeAccounts={claudeAccounts} limits={limits} />
      ) : (
        <>
          <div className="team-head">
            <h3>{t("new.drawn")}</h3>
            <button type="button" className="btn btn-small" onClick={onDrawAnother} disabled={!team}>
              <ShuffleIcon size={14} /> {t("new.drawAnother")}
            </button>
          </div>
          {team ? (
            <ul className="team-grid">
              {team.employees.map((member, i) => (
                <li key={member.name} className="member-card">
                  <Avatar name={member.name} size={36} />
                  <div>
                    <div className="member-name">{member.name} <span className="badge">{member.model}</span></div>
                    <div className="member-title">
                      {member.title}{member.name === rapporteur && t("new.alsoRapporteur")}
                    </div>
                    <div className="chips">
                      {traitChips(member, personality).map((chip) => (
                        <span key={chip.text} className={`chip${chip.strong ? " chip-strong" : ""}`}>{chip.text}</span>
                      ))}
                      <span className="chip chip-style">{member.style.tone}</span>
                    </div>
                    {claudeAccounts > 1 && (
                      <AccountSelect value={accounts[member.name] ?? null} effective={effective[i]} count={claudeAccounts}
                        onChange={(account) => {
                          const { [member.name]: _, ...rest } = accounts;
                          onAccountsChange(account === null ? rest : { ...rest, [member.name]: account });
                        }} />
                    )}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">{t("new.drawing")}</p>
          )}
          {team && (
            <label className="narrow">
              {t("new.rapporteur")}
              <select value={rapporteur ?? ""} onChange={(e) => onRapporteurChange(e.target.value || null)}>
                <option value="">{t("new.drawn")}</option>
                {team.employees.map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
              </select>
            </label>
          )}
        </>
      )}
      {custom && custom.length > 0 && !custom.some((m) => m.roles.includes("rapporteur")) && (
        <p className="muted">{t("new.noRapporteur")}</p>
      )}
      {problems.map((problem) => <p key={problem} className="error">{problem}</p>)}
    </section>
  );
}
