import { useCallback, useEffect, useState } from "react";
import { api, type CatalogLimits, type PersonalityPreset, type Role } from "../api";
import { useMounted } from "./useMounted";

export type TeamCatalog = {
  roles: Record<string, Role>;
  presets: Record<string, PersonalityPreset>;
  limits: CatalogLimits;
};

export type TeamCatalogState = {
  catalog: TeamCatalog | null; // null until loaded
  failed: boolean;
  retry: () => void;
};

/** Roles, personalities and limits the team section needs, loaded together: one failure fails the section. */
export function useTeamCatalog(): TeamCatalogState {
  const mounted = useMounted();
  const [catalog, setCatalog] = useState<TeamCatalog | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    Promise.all([api.roles(), api.personalities(), api.limits()])
      .then(([roles, presets, limits]) => mounted.current && setCatalog({ roles, presets, limits }))
      .catch(() => mounted.current && setFailed(true));
  }, [attempt, mounted]);

  const retry = useCallback(() => {
    setFailed(false);
    setAttempt((count) => count + 1);
  }, []);

  return { catalog, failed, retry };
}
