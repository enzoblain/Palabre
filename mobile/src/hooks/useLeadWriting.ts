import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { LIST_POLL_MS } from "./useConversations";
import { usePolling } from "./usePolling";

/** Whether the lead is writing in a project's direction room (the flag of the project list, as on the web). */
export function useLeadWriting(projectId: number): boolean {
  const [writing, setWriting] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    try {
      const projects = await api.listProjects();
      if (mounted.current) setWriting(projects.find((project) => project.id === projectId)?.lead_writing ?? false);
    } catch {
      if (mounted.current) setWriting(false);
    }
  }, [projectId]);

  usePolling(reload, LIST_POLL_MS);
  return writing;
}
