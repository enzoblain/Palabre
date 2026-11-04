import { useEffect, useRef, useState } from "react";
import type { AppleEnrollmentCode } from "../api";
import { useI18n } from "../i18n";
import { copyText, parseDate } from "../util";
import { Modal } from "./ConfirmDialog";

const SECONDS_PER_MINUTE = 60;
// setTimeout fires at once past this delay (32-bit signed)
const MAX_TIMEOUT_MS = 2 ** 31 - 1;

/** Shows the one-time code of a Mac (plain, selectable text), its lifetime from the API, and what to do once it expired. */
export function EnrollmentCodeDialog({ enrollment, regenerating, failed, onRegenerate, onClose }: {
  enrollment: AppleEnrollmentCode;
  regenerating: boolean;
  failed: boolean;
  onRegenerate: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [expired, setExpired] = useState(false);
  const [copied, setCopied] = useState<boolean | null>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setExpired(false);
    setCopied(null);
    const timer = window.setTimeout(() => setExpired(true), Math.min(MAX_TIMEOUT_MS, Math.max(0, parseDate(enrollment.expires_at).getTime() - Date.now())));
    return () => window.clearTimeout(timer);
  }, [enrollment]);

  // The Copy button is replaced when the code expires: keep the focus on the new primary button
  useEffect(() => { if (expired) primaryRef.current?.focus(); }, [expired]);

  async function copy() {
    setCopied(await copyText(enrollment.code));
  }

  const minutes = Math.max(1, Math.round(enrollment.ttl_seconds / SECONDS_PER_MINUTE));
  return (
    <Modal titleId="code-title" title={t("mac.codeTitle")} canClose onClose={onClose} initialFocus={primaryRef}>
      {expired ? (
        <p role="status" className="error">{t("mac.codeExpired")}</p>
      ) : (
        <>
          <p className="muted">{t("mac.codeIntro", { minutes })}</p>
          <code className="enrollment-code">{enrollment.code}</code>
        </>
      )}
      <div role="status" className="muted">
        {copied === true && t("mac.codeCopied")}
        {copied === false && t("mac.codeCopyFailed")}
      </div>
      {failed && <p role="alert" className="error">{t("mac.codeError")}</p>}
      <div className="row modal-actions">
        <button type="button" className="btn" onClick={onClose}>{t("common.close")}</button>
        {expired ? (
          <button ref={primaryRef} type="button" className="btn btn-primary" aria-disabled={regenerating}
            onClick={() => { if (!regenerating) onRegenerate(); }}>
            {regenerating ? t("mac.generating") : t("mac.codeRegenerate")}
          </button>
        ) : (
          <button ref={primaryRef} type="button" className="btn btn-primary" onClick={() => void copy()}>{t("mac.codeCopy")}</button>
        )}
      </div>
    </Modal>
  );
}
