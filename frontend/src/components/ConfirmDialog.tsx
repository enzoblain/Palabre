import { useEffect, useRef } from "react";
import { trappedFocusIndex } from "../devices";
import { useI18n } from "../i18n";

const FOCUSABLE = "button";

/** Modal confirmation: focus is trapped inside, Escape cancels and focus returns to the opener (if it is gone, the caller moves it). */
export function ConfirmDialog({ title, confirmLabel, busy, onConfirm, onCancel }: {
  title: string;
  confirmLabel: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    cancelRef.current?.focus();
    return () => { if (opener?.isConnected) opener.focus(); };
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      if (!busy) onCancel();
      return;
    }
    if (e.key !== "Tab") return;
    const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    if (items.length === 0) return;
    e.preventDefault();
    const current = items.indexOf(document.activeElement as HTMLElement);
    items[trappedFocusIndex(items.length, current, e.shiftKey)].focus();
  }

  return (
    <div className="modal-backdrop">
      <div ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title" onKeyDown={onKeyDown}>
        <p id="confirm-title" className="modal-title">{title}</p>
        <div className="row modal-actions">
          <button ref={cancelRef} type="button" className="btn" aria-disabled={busy} onClick={() => { if (!busy) onCancel(); }}>{t("common.cancel")}</button>
          <button type="button" className="btn btn-primary" aria-disabled={busy} onClick={() => { if (!busy) onConfirm(); }}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
