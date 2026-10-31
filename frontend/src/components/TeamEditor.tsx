import { useState } from "react";
import type { MemberIn, Personality, Role } from "../api";
import { spreadAccounts } from "../util";
import { AccountSelect } from "./AccountSelect";
import { Avatar } from "./Avatar";
import { ShuffleIcon } from "./Icons";

export const MAX_AGENTS = 30;
const NAME_RE = /^[\p{L}\p{N}_-]{1,40}$/u;
const MODELS = ["haiku", "sonnet", "opus"];

function pick<T>(items: T[]): T {
  return items[Math.floor(Math.random() * items.length)];
}

/** A random personality, like the server draws one. */
export function randomPersonality(personality: Personality): Pick<MemberIn, "traits" | "quirks" | "style"> {
  const quirks = [...personality.quirks].sort(() => Math.random() - 0.5).slice(0, 1 + Math.floor(Math.random() * 2));
  return {
    traits: Object.fromEntries(personality.axes.map((a) => [a.key, pick(personality.levels)])),
    quirks,
    style: Object.fromEntries(Object.entries(personality.style).map(([k, values]) => [k, pick(values)])),
  };
}

/** A blank agent, filled in by the boss: no name, no role, neutral opinions. */
export function newMember(personality: Personality): MemberIn {
  return {
    name: "",
    roles: [],
    model: null,
    account: null,
    traits: Object.fromEntries(personality.axes.map((a) => [a.key, 0])),
    quirks: [],
    // The middle option of each style (e.g. "balanced"), not an extreme
    style: Object.fromEntries(Object.entries(personality.style).map(([k, v]) => [k, v[Math.floor((v.length - 1) / 2)]])),
  };
}

/** A first name from the catalog nobody in the team has yet. */
function freeName(names: string[], taken: string[]): string {
  const free = names.filter((n) => !taken.some((t) => t.toLowerCase() === n.toLowerCase()));
  return free.length ? pick(free) : "";
}

/** Problems that keep the team from being created (the server checks them too).
 * needsLead: a company needs one (they organize the work and merge). */
export function teamProblems(members: MemberIn[], needsLead: boolean): string[] {
  const problems: string[] = [];
  if (!members.length) problems.push("Add at least one agent.");
  if (needsLead && members.length && !members.some((m) => m.roles.includes("lead"))) {
    problems.push("The team needs a lead: they organize the work and merge.");
  }
  const names = members.map((m) => m.name.toLowerCase());
  if (new Set(names).size !== names.length) problems.push("Two agents have the same name.");
  if (members.some((m) => !m.name)) problems.push("Every agent needs a name.");
  if (members.some((m) => m.name && !NAME_RE.test(m.name))) problems.push("Names are one word (letters, digits, - or _), so the team can @mention them.");
  if (members.some((m) => !m.roles.length)) problems.push("Every agent needs at least one role.");
  return problems;
}

function poleWord(text: string): string {
  return text.split(" — ")[0];
}

export function TeamEditor({ members, onChange, roles, personality, names, claudeAccounts }: {
  members: MemberIn[];
  onChange: (members: MemberIn[]) => void;
  roles: Record<string, Role>;
  personality: Personality;
  names: string[];
  claudeAccounts: number;
}) {
  const [open, setOpen] = useState<number | null>(null);
  const effective = spreadAccounts(members.map((m) => m.account), claudeAccounts);

  const update = (i: number, changes: Partial<MemberIn>) =>
    onChange(members.map((m, j) => (j === i ? { ...m, ...changes } : m)));

  function resize(count: number) {
    const n = Math.max(0, Math.min(MAX_AGENTS, count || 0));
    if (n <= members.length) return onChange(members.slice(0, n));
    const added = [...members];
    while (added.length < n) added.push(newMember(personality));
    onChange(added);
    setOpen(members.length); // Open the first new agent to fill it in
  }

  return (
    <div className="team-editor">
      <label className="narrow">
        Number of agents
        <input type="number" min={0} max={MAX_AGENTS} value={members.length}
          onChange={(e) => resize(Number(e.target.value))} />
      </label>

      {members.length === 0 && <p className="muted">No agent yet: add them one by one, or set their number.</p>}
      <ul className="editor-list">
        {members.map((m, i) => (
          <li key={i} className="editor-card">
            <div className="editor-head">
              <Avatar name={m.name || "?"} size={32} />
              <input className="editor-name" value={m.name} maxLength={40} aria-label="Nom" placeholder="Name"
                onChange={(e) => update(i, { name: e.target.value.replace(/\s/g, "") })} />
              <button type="button" className="icon-btn" title="Pick a first name"
                onClick={() => update(i, { name: freeName(names, members.map((x) => x.name)) })}>
                <ShuffleIcon size={14} />
              </button>
              <span className="muted truncate editor-summary">
                {m.roles.map((r) => roles[r]?.title ?? r).join(" + ") || "No role"}
              </span>
              <button type="button" className="btn btn-small" onClick={() => setOpen(open === i ? null : i)}>
                {open === i ? "Close" : "Edit"}
              </button>
              <button type="button" className="btn btn-small"
                onClick={() => {
                  onChange(members.filter((_, j) => j !== i));
                  setOpen(null);
                }}>Remove</button>
            </div>

            <div className="role-chips">
              {Object.entries(roles).map(([key, role]) => (
                <button type="button" key={key} title={role.mission}
                  className={`chip role-chip${m.roles.includes(key) ? " selected" : ""}`}
                  onClick={() => update(i, {
                    roles: m.roles.includes(key) ? m.roles.filter((r) => r !== key) : [...m.roles, key],
                  })}>
                  {role.title}
                </button>
              ))}
            </div>

            {open === i && (
              <div className="editor-details">
                <div className="row">
                  <label>
                    Model
                    <select value={m.model ?? ""} onChange={(e) => update(i, { model: e.target.value || null })}>
                      <option value="">Auto (from the roles)</option>
                      {MODELS.map((model) => <option key={model} value={model}>{model}</option>)}
                    </select>
                  </label>
                  {Object.entries(personality.style).map(([key, values]) => (
                    <label key={key}>
                      {key[0].toUpperCase() + key.slice(1)}
                      <select value={m.style[key] ?? ""} onChange={(e) => update(i, { style: { ...m.style, [key]: e.target.value } })}>
                        {values.map((v) => <option key={v} value={v}>{v}</option>)}
                      </select>
                    </label>
                  ))}
                  {claudeAccounts > 1 && (
                    <label>
                      Claude account
                      <AccountSelect value={m.account} effective={effective[i]} count={claudeAccounts}
                        onChange={(account) => update(i, { account })} />
                    </label>
                  )}
                  <button type="button" className="btn btn-small randomize"
                    onClick={() => update(i, randomPersonality(personality))}>
                    <ShuffleIcon size={14} /> Random personality
                  </button>
                </div>

                <div className="axes">
                  {personality.axes.map((axis) => (
                    <div key={axis.key} className="axis" title={axis.label}>
                      <span className="axis-pole" title={axis.low}>{poleWord(axis.low)}</span>
                      <input type="range" min={-2} max={2} step={1} value={m.traits[axis.key] ?? 0}
                        aria-label={axis.label}
                        onChange={(e) => update(i, { traits: { ...m.traits, [axis.key]: Number(e.target.value) } })} />
                      <span className="axis-pole" title={axis.high}>{poleWord(axis.high)}</span>
                    </div>
                  ))}
                </div>

                <div className="quirks">
                  <span className="muted">Quirks (up to 5)</span>
                  {[...new Set([...personality.quirks, ...m.quirks])].map((q) => (
                    <label key={q} className="quirk">
                      <input type="checkbox" checked={m.quirks.includes(q)}
                        disabled={!m.quirks.includes(q) && m.quirks.length >= 5}
                        onChange={() => update(i, { quirks: m.quirks.includes(q) ? m.quirks.filter((x) => x !== q) : [...m.quirks, q] })} />
                      {q}
                    </label>
                  ))}
                  <CustomQuirk disabled={m.quirks.length >= 5}
                    onAdd={(q) => !m.quirks.includes(q) && update(i, { quirks: [...m.quirks, q] })} />
                </div>
              </div>
            )}
          </li>
        ))}
      </ul>

      <button type="button" className="btn btn-small" disabled={members.length >= MAX_AGENTS}
        onClick={() => resize(members.length + 1)}>+ Add an agent</button>
    </div>
  );
}

function CustomQuirk({ disabled, onAdd }: { disabled: boolean; onAdd: (quirk: string) => void }) {
  const [text, setText] = useState("");
  const add = () => {
    if (text.trim()) onAdd(text.trim().slice(0, 200));
    setText("");
  };
  return (
    <div className="row custom-quirk">
      <input value={text} disabled={disabled} maxLength={200} placeholder="Your own quirk, e.g. You quote Linus Torvalds in every review."
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            add();
          }
        }} />
      <button type="button" className="btn btn-small" disabled={disabled || !text.trim()} onClick={add}>Add</button>
    </div>
  );
}
