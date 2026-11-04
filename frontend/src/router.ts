import { useEffect, useState } from "react";

// Hash routes: #/  #/new  #/settings  #/p/<project>  #/p/<project>/c/<conversation>  #/p/<project>/info  #/p/<project>/tasks  #/p/<project>/tasks/<task>
export type Route =
  | { name: "home" }
  | { name: "new" }
  | { name: "settings" }
  | { name: "project"; projectId: number; conversationId: number | null }
  | { name: "info"; projectId: number }
  | { name: "tasks"; projectId: number }
  | { name: "task"; projectId: number; taskId: number };

function parse(hash: string): Route {
  const path = hash.replace(/^#/, "");
  if (path === "/new") return { name: "new" };
  if (path === "/settings") return { name: "settings" };
  const info = path.match(/^\/p\/(\d+)\/info$/);
  if (info) return { name: "info", projectId: Number(info[1]) };
  const tasks = path.match(/^\/p\/(\d+)\/tasks$/);
  if (tasks) return { name: "tasks", projectId: Number(tasks[1]) };
  const task = path.match(/^\/p\/(\d+)\/tasks\/(\d+)$/);
  if (task) return { name: "task", projectId: Number(task[1]), taskId: Number(task[2]) };
  const m = path.match(/^\/p\/(\d+)(?:\/c\/(\d+))?$/);
  if (m) return { name: "project", projectId: Number(m[1]), conversationId: m[2] ? Number(m[2]) : null };
  return { name: "home" };
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash));
  useEffect(() => {
    const update = () => setRoute(parse(location.hash));
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  return route;
}

export function go(path: string, replace = false): void {
  if (replace) {
    history.replaceState(null, "", `#${path}`);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    location.hash = path;
  }
}

