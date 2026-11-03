import { useEffect, useState } from "react";
import { ApiError, type CatalogLimits, type Employee, type PersonalityPreset, type Role, api } from "../api";
import { useI18n } from "../i18n";
import { Avatar } from "./Avatar";
import { JobPicker } from "./JobPicker";
import { PersonalityPicker } from "./PersonalityPicker";

type Catalog = { roles: Record<string, Role>; presets: Record<string, PersonalityPreset>; limits: CatalogLimits };

const errorText = (err: unknown): string => (err instanceof ApiError ? err.message : String(err));

function useCatalog(): { catalog: Catalog | null; failed: boolean } {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    Promise.all([api.roles(), api.personalities(), api.limits()])
      .then(([roles, presets, limits]) => setCatalog({ roles, presets, limits }))
      .catch(() => setFailed(true));
  }, []);
  return { catalog, failed };
}

/** Roles and personality of one member (a new one when `member` is absent), saved with one request. */
function MemberForm({ member, catalog, submitLabel, busy, error, onSubmit, onCancel }: {
  member?: Employee;
  catalog: Catalog;
  submitLabel: string;
  busy: boolean;
  error: string | null;
  onSubmit: (roles: string[], personality: string | null) => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const [roles, setRoles] = useState<string[]>(member?.roles ?? []);
  const [personality, setPersonality] = useState<string | null>(null);
  return (
    <form className="editor-details" onSubmit={(e) => { e.preventDefault(); onSubmit(roles, personality); }}>
      <JobPicker roles={catalog.roles} selected={roles} onChange={setRoles} />
      <PersonalityPicker presets={catalog.presets} selected={personality} onSelect={setPersonality} />
      <p className="muted">{t(member ? "team.editHint" : "team.addHint")}</p>
      {roles.length === 0 && <p className="muted">{t("team.noRole")}</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="row">
        <button type="button" className="btn btn-small" onClick={onCancel} disabled={busy}>{t("common.cancel")}</button>
        <button className="btn btn-small btn-primary" disabled={busy || roles.length === 0}>{submitLabel}</button>
      </div>
    </form>
  );
}

/** A member of the team: roles and personality, with edit and remove (confirmed) unless they are the lead. */
function MemberCard({ member, catalog, onChanged }: { member: Employee; catalog: Catalog; onChanged: () => void }) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"idle" | "editing" | "removing">("idle");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isLead = member.roles.includes(catalog.limits.mandatory_role);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      setMode("idle");
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const close = () => { setMode("idle"); setError(null); };
  const save = (roles: string[], personality: string | null) => run(() => api.updateEmployee(member.id, {
    roles, ...(personality ? { personality } : {}),
  }));

  return (
    <li className="editor-card">
      <div className="team-member-head">
        <Avatar name={member.name} size={34} />
        <span className="team-member-text">
          <span className="truncate">{member.name}</span>
          <span className="member-role truncate">{member.title}</span>
          {member.quirks.length > 0 && <span className="member-role truncate">{member.quirks.join(" · ")}</span>}
        </span>
        {isLead ? (
          <span className="badge" title={t("team.leadLocked")}>{t("team.lead")}</span>
        ) : mode === "idle" && (
          <>
            <button className="btn btn-small" aria-label={t("team.editAria", { name: member.name })}
              onClick={() => setMode("editing")}>{t("common.edit")}</button>
            <button className="btn btn-small" aria-label={t("team.removeAria", { name: member.name })}
              onClick={() => setMode("removing")}>{t("common.remove")}</button>
          </>
        )}
      </div>
      {mode === "editing" && (
        <MemberForm member={member} catalog={catalog} submitLabel={busy ? t("common.saving") : t("common.save")}
          busy={busy} error={error} onSubmit={save} onCancel={close} />
      )}
      {mode === "removing" && (
        <div className="editor-details">
          <span className="error">{t("team.removeConfirm", { name: member.name })}</span>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="row confirm-delete">
            <button className="btn btn-small" onClick={close} disabled={busy}>{t("common.cancel")}</button>
            <button className="btn btn-small btn-danger" disabled={busy}
              onClick={() => run(() => api.removeEmployee(member.id))}>
              {busy ? t("team.removing") : t("team.removeForGood")}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

function AddMember({ projectId, catalog, onChanged }: { projectId: number; catalog: Catalog; onChanged: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add(roles: string[], personality: string | null) {
    setBusy(true);
    setError(null);
    try {
      await api.addEmployee(projectId, { roles, personality });
      setOpen(false);
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  if (!open) return <button className="btn btn-small" onClick={() => setOpen(true)}>{t("team.add")}</button>;
  return (
    <div className="editor-card">
      <h3 className="section-label">{t("team.addTitle")}</h3>
      <MemberForm catalog={catalog} submitLabel={busy ? t("team.adding") : t("common.add")} busy={busy}
        error={error} onSubmit={add} onCancel={() => { setOpen(false); setError(null); }} />
    </div>
  );
}

/** The team in the project info: list with roles and personality, add, edit and remove members. */
export function TeamSection({ projectId, members, onChanged }: {
  projectId: number;
  members: Employee[];
  /** A member was added, edited or removed: reload the project */
  onChanged: () => void;
}) {
  const { t } = useI18n();
  const { catalog, failed } = useCatalog();
  const sorted = [...members].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <section className="team-members" aria-labelledby="info-members">
      <h2 className="section-label" id="info-members">{t("info.members")}</h2>
      {failed && <p className="error" role="alert">{t("team.loadError")}</p>}
      {!catalog && !failed && <p className="muted">{t("common.loading")}</p>}
      {catalog && (
        <>
          {sorted.length === 0 && <p className="muted">{t("team.empty")}</p>}
          <ul className="editor-list">
            {sorted.map((m) => <MemberCard key={m.id} member={m} catalog={catalog} onChanged={onChanged} />)}
          </ul>
          <AddMember projectId={projectId} catalog={catalog} onChanged={onChanged} />
        </>
      )}
    </section>
  );
}
