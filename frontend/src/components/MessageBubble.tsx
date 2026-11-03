import { memo, useEffect, useRef, useState } from "react";
import type { Message } from "../api";
import { locale, useI18n } from "../i18n";
import { copyText, parseDate } from "../util";
import { Markdown, mentionsAny } from "./Markdown";

const LONG_PRESS_MS = 500;
const COPIED_FEEDBACK_MS = 1500;

/** Full date and time a message was sent, for the Info action. */
function formatSentAt(value: string): string {
  return parseDate(value).toLocaleString(locale(), { dateStyle: "long", timeStyle: "medium" });
}

const COPY_LABEL_KEYS = {
  idle: "conv.copy",
  copied: "conv.copied",
  failed: "conv.copyFailed",
} as const;

/** The Copy and Info actions of a bubble; Info shows when the message was sent. */
function BubbleMenu({ message, onClose }: { message: Message; onClose: () => void }) {
  const { t } = useI18n();
  const [showInfo, setShowInfo] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const ref = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(closeTimer.current), []);

  useEffect(() => {
    ref.current?.querySelector("button")?.focus();
    const onPointerDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose]);

  async function copy() {
    const succeeded = await copyText(message.content);
    setCopyState(succeeded ? "copied" : "failed");
    if (succeeded) closeTimer.current = window.setTimeout(onClose, COPIED_FEEDBACK_MS);
  }

  return (
    <div className="bubble-menu" role="menu" ref={ref}>
      <button role="menuitem" onClick={copy}>{t(COPY_LABEL_KEYS[copyState])}</button>
      <button role="menuitem" aria-expanded={showInfo} onClick={() => setShowInfo(true)}>{t("conv.info")}</button>
      {showInfo && <p className="bubble-info" role="status">{t("conv.sentAt", { date: formatSentAt(message.created_at) })}</p>}
    </div>
  );
}

/** One message as a bubble: the boss's on the right, everyone else's on the left. Memoized: re-parsing every
 * message's Markdown on each render made typing slow. */
export const MessageRow = memo(function MessageRow({ message: m, grouped, title, selfNames }: {
  message: Message;
  grouped: boolean;
  title: string | undefined;
  selfNames: string[];
}) {
  const { t } = useI18n();
  const [menuOpen, setMenuOpen] = useState(false);
  const pressTimer = useRef<number | undefined>(undefined);
  const system = m.is_system;
  const boss = m.employee_id === null && !system;
  const forMe = !boss && !system && mentionsAny(m.content, selfNames);
  const body = <div className="message-body"><Markdown content={m.content} selfNames={selfNames} /></div>;

  const cancelPress = () => window.clearTimeout(pressTimer.current);
  const startPress = () => {
    cancelPress();
    pressTimer.current = window.setTimeout(() => setMenuOpen(true), LONG_PRESS_MS);
  };
  useEffect(() => cancelPress, []);

  return (
    <div id={`message-${m.id}`} tabIndex={-1} className={`message${grouped ? " grouped" : ""}${boss ? " from-boss" : ""}${system ? " from-system" : ""}${forMe ? " mentions-me" : ""}`}>
      <div className="bubble-wrap">
        {!grouped && !boss && (
          <div className="message-meta">
            <strong>{m.author_name}</strong>
            <span className="muted">{system ? t("conv.platform") : title}</span>
          </div>
        )}
        <div className="bubble" onPointerDown={startPress} onPointerUp={cancelPress} onPointerLeave={cancelPress}
          onPointerCancel={cancelPress}
          onContextMenu={(e) => { e.preventDefault(); setMenuOpen(true); }}>
          {body}
          <button className="bubble-more" aria-label={t("conv.actions")} aria-haspopup="menu" aria-expanded={menuOpen}
            onClick={() => setMenuOpen(true)}>⋯</button>
        </div>
        {menuOpen && <BubbleMenu message={m} onClose={() => setMenuOpen(false)} />}
      </div>
    </div>
  );
});

/** The three animated dots shown while the lead is writing. */
export function TypingDots({ name }: { name: string }) {
  const { t } = useI18n();
  return (
    <div className="message typing" role="status" aria-label={t("conv.typing", { name })}>
      <div className="bubble-wrap">
        <div className="bubble typing-bubble" aria-hidden="true"><span /><span /><span /></div>
      </div>
    </div>
  );
}
