import { useI18n } from "../i18n";
import type { Route } from "../router";
import { GearIcon, PlusIcon, ProjectsIcon } from "./Icons";

const ITEMS = [
  { route: "home", href: "#/", label: "nav.projects", Icon: ProjectsIcon },
  { route: "new", href: "#/new", label: "nav.newProject", Icon: PlusIcon },
  { route: "settings", href: "#/settings", label: "nav.settings", Icon: GearIcon },
] as const;

/** Floating bar of the phone layout; hidden by CSS on large screens. */
export function BottomBar({ route }: { route: Route }) {
  const { t } = useI18n();
  return (
    <nav className="bottom-bar" aria-label={t("nav.label")}>
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
