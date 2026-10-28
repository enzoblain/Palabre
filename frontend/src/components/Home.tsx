import { go } from "../router";
import { PlusIcon } from "./Icons";

export function Home({ hasProjects }: { hasProjects: boolean }) {
  return (
    <div className="home">
      <button className="big-plus" onClick={() => go("/new")} aria-label="New project">
        <PlusIcon size={44} />
      </button>
      <p className="home-caption">{hasProjects ? "New project" : "Create your first project"}</p>
    </div>
  );
}
