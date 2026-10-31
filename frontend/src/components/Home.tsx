import { useI18n } from "../i18n";
import { go } from "../router";
import { PlusIcon } from "./Icons";

export function Home({ hasProjects }: { hasProjects: boolean }) {
  const { t } = useI18n();
  return (
    <div className="home">
      <button className="big-plus" onClick={() => go("/new")} aria-label={t("home.newProjectAria")}>
        <PlusIcon size={44} />
      </button>
      <p className="home-caption">{hasProjects ? t("home.newProject") : t("home.firstProject")}</p>
    </div>
  );
}
