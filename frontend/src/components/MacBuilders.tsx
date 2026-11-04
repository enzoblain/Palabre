import { useCallback, useRef, useState } from "react";
import { type AppleEnrollmentCode, type AppleHost, api } from "../api";
import { isAppleModeOff, relativeTime, sortBySeen } from "../apple";
import { locale, useI18n } from "../i18n";
import { parseDate, usePolling } from "../util";
import { ConfirmDialog } from "./ConfirmDialog";
import { EnrollmentCodeDialog } from "./EnrollmentCodeDialog";
import { DotEmptyIcon, DotFilledIcon } from "./Icons";

const REFRESH_MS = 30_000;

/** Settings section: the Mac builders, their state, their revocation and the one-time enrollment code. */
export function MacBuilders() {
  const { t } = useI18n();
  const [hosts, setHosts] = useState<AppleHost[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [modeOff, setModeOff] = useState(false);
  const [pending, setPending] = useState<AppleHost | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revokeFailed, setRevokeFailed] = useState(false);
  const [enrollment, setEnrollment] = useState<AppleEnrollmentCode | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateFailed, setGenerateFailed] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const previous = useRef<AppleHost[] | null>(null);

  const refresh = useCallback(async () => {
    try {
      const next = sortBySeen((await api.listAppleHosts()).filter((host) => !host.revoked_at));
      announceLostMac(previous.current, next);
      previous.current = next;
      setHosts(next);
      setLoadError(false);
    } catch (err) {
      if (isAppleModeOff(err)) setModeOff(true);
      else if (previous.current === null) setLoadError(true);
    }
  }, [t]); // eslint-disable-line react-hooks/exhaustive-deps
  usePolling(modeOff ? null : refresh, REFRESH_MS, [modeOff, refresh]);

  // Only a Mac that was connected and no longer is deserves a live announcement
  function announceLostMac(before: AppleHost[] | null, after: AppleHost[]) {
    const wasConnected = new Set(before?.filter((host) => host.connected).map((host) => host.id));
    const lost = after.find((host) => wasConnected.has(host.id) && !host.connected);
    if (lost) setAnnouncement(t("mac.nowOffline", { name: lost.name }));
  }

  async function revoke(host: AppleHost) {
    setRevoking(true);
    setRevokeFailed(false);
    try {
      await api.revokeAppleHost(host.id);
      setPending(null);
      setAnnouncement(t("mac.revoked"));
      await refresh();
    } catch {
      setRevokeFailed(true);
    } finally {
      setRevoking(false);
    }
  }

  async function generate() {
    setGenerating(true);
    setGenerateFailed(false);
    try {
      setEnrollment(await api.createAppleEnrollmentCode());
    } catch {
      setGenerateFailed(true);
    } finally {
      setGenerating(false);
    }
  }

  // The section only exists while Apple mode is on
  if (modeOff) return null;
  return (
    <section className="panel" aria-labelledby="mac-title" aria-busy={hosts === null && !loadError}>
      <h2 id="mac-title">{t("mac.title")}</h2>
      {hosts === null && !loadError && <p className="muted">{t("mac.loading")}</p>}
      {loadError && (
        <div className="row">
          <p role="alert" className="error">{t("mac.loadError")}</p>
          <button className="btn btn-small" onClick={() => { setLoadError(false); void refresh(); }}>{t("common.retry")}</button>
        </div>
      )}
      {hosts?.length === 0 && <p className="muted">{t("mac.empty")}</p>}
      {hosts && hosts.length > 0 && (
        <ul className="device-list">
          {hosts.map((host) => <MacRow key={host.id} host={host} onRevoke={() => { setRevokeFailed(false); setPending(host); }} />)}
        </ul>
      )}
      {hosts && (
        <div className="row">
          <button className="btn btn-primary" aria-disabled={generating} onClick={() => { if (!generating) void generate(); }}>
            {generating ? t("mac.generating") : t("mac.generate")}
          </button>
        </div>
      )}
      {generateFailed && !enrollment && <p role="alert" className="error">{t("mac.codeError")}</p>}
      <div role="status" className="muted">{announcement}</div>
      {pending && (
        <ConfirmDialog title={t("mac.revokeTitle", { name: pending.name })} confirmLabel={revoking ? t("mac.revoking") : t("mac.revoke")}
          busy={revoking} onConfirm={() => void revoke(pending)} onCancel={() => setPending(null)}>
          {revokeFailed && <p role="alert" className="error">{t("mac.revokeError")}</p>}
        </ConfirmDialog>
      )}
      {enrollment && (
        <EnrollmentCodeDialog enrollment={enrollment} regenerating={generating} failed={generateFailed}
          onRegenerate={() => void generate()} onClose={() => { setEnrollment(null); setGenerateFailed(false); }} />
      )}
    </section>
  );
}

function MacRow({ host, onRevoke }: { host: AppleHost; onRevoke: () => void }) {
  const { t } = useI18n();
  const seen = host.last_seen_at ? parseDate(host.last_seen_at) : null;
  return (
    <li>
      <div className="device-info">
        <strong className="truncate">{host.name}</strong>
        <span className={host.connected ? "mac-state mac-online" : "mac-state"}>
          {host.connected ? <DotFilledIcon size={14} /> : <DotEmptyIcon size={14} />}
          {host.connected ? t("mac.connected") : t("mac.offline")}
        </span>
        <span className="muted">
          {seen
            ? <time dateTime={seen.toISOString()} title={seen.toLocaleString(locale())}>{t("mac.lastSeen", { when: relativeTime(seen, new Date(), locale()) })}</time>
            : t("mac.neverSeen")}
        </span>
        {!host.connected && <span className="muted">{t("mac.offlineConsequence")}</span>}
      </div>
      <button className="btn btn-small" aria-label={t("mac.revokeAria", { name: host.name })} onClick={onRevoke}>{t("mac.revoke")}</button>
    </li>
  );
}
