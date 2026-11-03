import { useEffect, useRef } from "react";
import { useI18n } from "../i18n";
import type { Route } from "../router";
import { GearIcon, PlusIcon, ProjectsIcon } from "./Icons";

const ITEMS = [
  { route: "home", href: "#/", label: "nav.projects", Icon: ProjectsIcon },
  { route: "new", href: "#/new", label: "nav.newProject", Icon: PlusIcon },
  { route: "settings", href: "#/settings", label: "nav.settings", Icon: GearIcon },
] as const;

const BAR_HEIGHT_VARIABLE = "--bottom-bar-height";

/** Publishes the real bar height as a CSS variable, so the page padding follows it when labels wrap. */
function useBarHeightVariable(barRef: React.RefObject<HTMLElement>) {
  useEffect(() => {
    const bar = barRef.current;
    if (!bar) return;
    const root = document.documentElement;
    const publish = () => root.style.setProperty(BAR_HEIGHT_VARIABLE, `${bar.getBoundingClientRect().height}px`);
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(bar);
    return () => {
      observer.disconnect();
      root.style.removeProperty(BAR_HEIGHT_VARIABLE);
    };
  }, [barRef]);
}

/** Floating bottom bar of the root screens, on every screen width. */
export function BottomBar({ route }: { route: Route }) {
  const { t } = useI18n();
  const barRef = useRef<HTMLElement>(null);
  useBarHeightVariable(barRef);
  return (
    <nav ref={barRef} className="bottom-bar" aria-label={t("nav.label")}>
      {ITEMS.map(({ route: name, href, label, Icon }) => (
        <a key={name} href={href} className={route.name === name ? "active" : undefined}
          aria-current={route.name === name ? "page" : undefined}>
          <Icon size={22} />
          <span>{t(label)}</span>
        </a>
      ))}
    </nav>
  );
}
