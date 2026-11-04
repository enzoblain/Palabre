import { type ReactNode, useEffect, useRef } from "react";
import { trappedFocusIndex } from "../devices";
import { useI18n } from "../i18n";

const FOCUSABLE = "button";

/** Modal shell: focus goes to `initialFocus`, is trapped inside, Escape closes and focus returns to the opener (if it is gone, the caller moves it). */
export function Modal({ titleId, title, canClose, onClose, initialFocus, children }: {
  titleId: string;
  title: string;
  canClose: boolean;
  onClose: () => void;
  initialFocus: React.RefObject<HTMLElement>;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    initialFocus.current?.focus();
    return () => { if (opener?.isConnected) opener.focus(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      e.stopPropagation();
      if (canClose) onClose();
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
      <div ref={dialogRef} className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <p id={titleId} className="modal-title">{title}</p>
        {children}
      </div>
    </div>
  );
}

/** Modal confirmation; `children` (an error, for instance) is shown under the title and the dialog stays open. */
export function ConfirmDialog({ title, confirmLabel, busy, onConfirm, onCancel, children }: {
  title: string;
  confirmLabel: string;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}) {
  const { t } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);

  return (
    <Modal titleId="confirm-title" title={title} canClose={!busy} onClose={onCancel} initialFocus={cancelRef}>
      {children}
      <div className="row modal-actions">
        <button ref={cancelRef} type="button" className="btn" aria-disabled={busy} onClick={() => { if (!busy) onCancel(); }}>{t("common.cancel")}</button>
        <button type="button" className="btn btn-primary" aria-disabled={busy} onClick={() => { if (!busy) onConfirm(); }}>{confirmLabel}</button>
      </div>
    </Modal>
  );
}
