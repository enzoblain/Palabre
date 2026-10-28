import { useEffect, useState } from "react";

// Hash routes: #/  #/new  #/settings  #/p/<project>  #/p/<project>/c/<conversation>  #/p/<project>/inbox
export type Route =
  | { name: "home" }
  | { name: "new" }
  | { name: "settings" }
  | { name: "project"; projectId: number; conversationId: number | null }
  | { name: "inbox"; projectId: number };

function parse(hash: string): Route {
  const path = hash.replace(/^#/, "");
  if (path === "/new") return { name: "new" };
  if (path === "/settings") return { name: "settings" };
  const inbox = path.match(/^\/p\/(\d+)\/inbox$/);
  if (inbox) return { name: "inbox", projectId: Number(inbox[1]) };
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
