import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, type Device, api } from "../api";
import { neverUsed, withoutDevice } from "../devices";
import { locale, useI18n } from "../i18n";
import { parseDate } from "../util";
import { ConfirmDialog } from "./ConfirmDialog";

type Outcome = { ok: boolean; text: string };

const formatDate = (value: string): string => parseDate(value).toLocaleString(locale(), { dateStyle: "long", timeStyle: "short" });
const errorText = (err: unknown): string => (err instanceof ApiError ? err.message : String(err));

/** Settings section: the paired phones, each revocable after a confirmation. */
export function ConnectedDevices() {
  const { t } = useI18n();
  const [devices, setDevices] = useState<Device[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [pending, setPending] = useState<Device | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const revokedIndexRef = useRef(0);

  const load = useCallback(async () => {
    setLoadError(null);
    setDevices(null);
    try {
      setDevices(await api.listDevices());
    } catch (err) {
      setLoadError(errorText(err));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  // The revoked row, and its button, are gone: focus the button of the row that took its place, else the title.
  useEffect(() => {
    if (!outcome?.ok) return;
    const buttons = listRef.current?.querySelectorAll<HTMLButtonElement>("li button");
    (buttons?.[revokedIndexRef.current] ?? titleRef.current)?.focus();
  }, [outcome]);

  async function revoke(device: Device) {
    setRevoking(true);
    try {
      await api.revokeDevice(device.id);
      revokedIndexRef.current = devices?.findIndex((item) => item.id === device.id) ?? 0;
      setDevices((current) => current && withoutDevice(current, device.id));
      setOutcome({ ok: true, text: t("settings.deviceRevoked") });
    } catch (err) {
      setOutcome({ ok: false, text: t("settings.deviceRevokeFailed", { message: errorText(err) }) });
    } finally {
      setRevoking(false);
      setPending(null);
    }
  }

  return (
    <section className="panel" aria-labelledby="devices-title" aria-busy={devices === null && !loadError}>
      <h2 id="devices-title" ref={titleRef} tabIndex={-1}>{t("settings.devices")}</h2>
      <p className="muted">{t("settings.devicesIntro")}</p>
      {devices === null && !loadError && <p role="status" className="muted">{t("settings.devicesLoading")}</p>}
      {loadError && (
        <div className="row">
          <p role="alert" className="error">{t("settings.devicesError", { message: loadError })}</p>
          <button className="btn btn-small" onClick={() => void load()}>{t("common.retry")}</button>
        </div>
      )}
      {devices?.length === 0 && <p className="muted">{t("settings.devicesEmpty")}</p>}
      {devices && devices.length > 0 && (
        <ul className="device-list" ref={listRef}>
          {devices.map((device) => (
            <li key={device.id}>
              <div className="device-info">
                <strong className="truncate">{device.name}</strong>
                <span className="muted">{t("settings.deviceAdded", { date: formatDate(device.created_at) })}</span>
                <span className="muted">
                  {t("settings.deviceLastUsed", { date: neverUsed(device) ? t("settings.deviceNeverUsed") : formatDate(device.last_used_at) })}
                </span>
                <span className="muted">{t("settings.deviceExpires", { date: formatDate(device.expires_at) })}</span>
              </div>
              <button className="btn btn-small" aria-label={t("settings.deviceRevokeAria", { name: device.name })}
                onClick={() => { setOutcome(null); setPending(device); }}>
                {t("settings.deviceRevoke")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div role="status">
        {outcome && <p className={outcome.ok ? "success" : "error"}>{outcome.text}</p>}
      </div>
      {pending && (
        <ConfirmDialog title={t("settings.deviceRevokeTitle", { name: pending.name })} confirmLabel={t("settings.deviceRevoke")}
          busy={revoking} onConfirm={() => void revoke(pending)} onCancel={() => setPending(null)} />
      )}
    </section>
  );
}
