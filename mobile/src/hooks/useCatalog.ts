import { useCallback, useEffect, useRef, useState } from "react";
import { api, type CatalogLimits, type PersonalityPreset, type Role } from "../api";
import { useMounted } from "./useMounted";

export type Catalog = {
  names: string[];
  limits: CatalogLimits | null;
  roles: Record<string, Role> | null;
  presets: Record<string, PersonalityPreset> | null;
  presetsFailed: boolean;
  retryPresets: () => void;
};

/**
 * The catalog the new project form needs. Names, limits and roles fail silently (the manual team stays
 * unavailable); the presets failure is reported with a retry, as on the web.
 */
export function useCatalog(): Catalog {
  const mounted = useMounted();
  const [names, setNames] = useState<string[]>([]);
  const [limits, setLimits] = useState<CatalogLimits | null>(null);
  const [roles, setRoles] = useState<Record<string, Role> | null>(null);
  const [presets, setPresets] = useState<Record<string, PersonalityPreset> | null>(null);
  const [presetsFailed, setPresetsFailed] = useState(false);
  // Identifies the latest presets request: a late answer from an earlier one is ignored
  const presetsRequest = useRef(0);

  const fetchPresets = useCallback(() => {
    const request = ++presetsRequest.current;
    const isLatest = () => mounted.current && request === presetsRequest.current;
    api.personalities()
      .then((loaded) => isLatest() && setPresets(loaded))
      .catch(() => isLatest() && setPresetsFailed(true));
  }, [mounted]);

  const retryPresets = useCallback(() => {
    setPresets(null);
    setPresetsFailed(false);
    fetchPresets();
  }, [fetchPresets]);

  useEffect(() => {
    api.names().then((loaded) => mounted.current && setNames(loaded)).catch(() => {});
    api.limits().then((loaded) => mounted.current && setLimits(loaded)).catch(() => {});
    api.roles().then((loaded) => mounted.current && setRoles(loaded)).catch(() => {});
    fetchPresets();
  }, [fetchPresets, mounted]);

  return { names, limits, roles, presets, presetsFailed, retryPresets };
}
