import { useCallback, useEffect, useState } from "react";
import { api, type ProjectDetail } from "../api";
import { useMounted } from "./useMounted";

export type ProjectState = {
  detail: ProjectDetail | null; // null until the first load
  failed: boolean;
  reload: () => Promise<void>;
};

/** One project with its rooms and employees, read on mount and on demand. */
export function useProject(projectId: number): ProjectState {
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const mounted = useMounted();

  useEffect(() => {
    api
      .getProject(projectId)
      .then((loaded) => {
        if (!mounted.current) return;
        setDetail(loaded);
        setFailed(false);
      })
      .catch(() => mounted.current && setFailed(true));
  }, [projectId, attempt]);
  const reload = useCallback(async () => setAttempt((count) => count + 1), []);

  return { detail, failed, reload };
}
