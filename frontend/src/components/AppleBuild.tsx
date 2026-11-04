import { useCallback, useRef, useState } from "react";
import { type AppleBuild as Build, api } from "../api";
import { isKnownStatus, isSettled, shortSha } from "../apple";
import { useI18n } from "../i18n";
import { usePolling } from "../util";
import { CheckIcon, ClockIcon, CrossIcon, SpinnerIcon, WarningIcon } from "./Icons";

const POLL_MS = 5000;

const ICONS = { queued: ClockIcon, running: SpinnerIcon, passed: CheckIcon, failed: CrossIcon, error: WarningIcon } as const;

/** "Swift build" block of a task: the newest build of its head, the reason of a failure and a retry after an infra error. */
export function AppleBuild({ taskId }: { taskId: number }) {
  const { t } = useI18n();
  const [build, setBuild] = useState<Build | null | undefined>(undefined);
  const [loadFailed, setLoadFailed] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryFailed, setRetryFailed] = useState(false);
  const [open, setOpen] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const lastStatus = useRef<string | null>(null);
  const loaded = useRef(false);

  const apply = useCallback((next: Build | null) => {
    // Announce a change of the newest build only, never the first display
    if (next && lastStatus.current !== null && lastStatus.current !== next.status) {
      setAnnouncement(t(`build.announce.${next.status}` as const));
    }
    lastStatus.current = next?.status ?? null;
    loaded.current = true;
    setBuild(next);
    setLoadFailed(false);
  }, [t]);

  const refresh = useCallback(async () => {
    try {
      apply((await api.getTaskBuild(taskId)).apple_build);
    } catch {
      if (!loaded.current) setLoadFailed(true);
    }
  }, [taskId, apply]);
  // Loads once, then keeps polling while the Mac has not given its verdict; the parent keys this block by task
  const polling = build === undefined || !isSettled(build);
  usePolling(polling ? refresh : null, POLL_MS, [taskId, polling]);

  async function retry() {
    setRetrying(true);
    setRetryFailed(false);
    try {
      apply((await api.retryAppleBuild(taskId)).apple_build);
    } catch {
      setRetryFailed(true);
    } finally {
      setRetrying(false);
    }
  }

  return (
    <section className="panel apple-build" aria-labelledby={`build-title-${taskId}`}>
      <h3 id={`build-title-${taskId}`} className="section-label">{t("build.title")}</h3>
      {build === undefined && !loadFailed && <p className="muted">{t("build.loading")}</p>}
      {loadFailed && (
        <div className="row">
          <p role="alert" className="error">{t("build.loadError")}</p>
          <button className="btn btn-small" onClick={() => { setLoadFailed(false); void refresh(); }}>{t("common.retry")}</button>
        </div>
      )}
      {build === null && <p className="muted">{t("build.none")}</p>}
      {build && (
        <>
          <BuildLine build={build} />
          {build.status === "error" && (
            <div className="build-retry">
              <p className="muted">{t("build.infraNote")}</p>
              <button className="btn btn-small" aria-disabled={retrying} onClick={() => { if (!retrying) void retry(); }}>
                {retrying ? t("build.retrying") : t("build.retry")}
              </button>
              {retryFailed && <p role="alert" className="error">{t("build.retryError")}</p>}
            </div>
          )}
          {build.summary && <p className="build-summary">{build.summary}</p>}
          {build.errors.length > 0 && (
            <>
              <button className="btn btn-small" aria-expanded={open} aria-controls={`build-log-${taskId}`} onClick={() => setOpen(!open)}>
                {open ? t("build.hideDetail") : t("build.showDetail")}
              </button>
              {/* Log lines are untrusted: plain text only, never HTML */}
              {open && <pre id={`build-log-${taskId}`} className="build-log" tabIndex={0} aria-label={t("build.log")}>{build.errors.join("\n")}</pre>}
            </>
          )}
        </>
      )}
      <div role="status" className="sr-only">{announcement}</div>
    </section>
  );
}

function BuildLine({ build }: { build: Build }) {
  const { t } = useI18n();
  if (!isKnownStatus(build.status)) {
    return <p className="build-line"><WarningIcon size={16} /><span>{t("build.unknown", { status: String(build.status) })}</span></p>;
  }
  const Icon = ICONS[build.status];
  return (
    <p className={`build-line build-${build.status}`}>
      <span className={build.status === "running" ? "spin" : undefined}><Icon size={16} /></span>
      <strong>{t(`build.status.${build.status}` as const)}</strong>
      <span className="muted">{t("build.commit", { sha: shortSha(build.commit_sha) })}</span>
    </p>
  );
}
