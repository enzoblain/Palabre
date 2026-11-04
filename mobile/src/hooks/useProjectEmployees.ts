import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Employee, type ProjectDetail } from "../api";

export type ProjectEmployeesState = {
  projects: ProjectDetail[] | null; // null until loaded
  failed: boolean;
  /** Pins an employee to a Claude account (null: spread automatically); rejects with the ApiError. */
  setAccount: (projectId: number, employeeId: number, account: number | null) => Promise<void>;
};

/** Every project with its employees, loaded only when `enabled` (several Claude accounts). */
export function useProjectEmployees(enabled: boolean): ProjectEmployeesState {
  const [projects, setProjects] = useState<ProjectDetail[] | null>(null);
  const [failed, setFailed] = useState(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    api
      .listProjects()
      .then((items) => Promise.all(items.map((item) => api.getProject(item.id))))
      .then((details) => mounted.current && setProjects(details))
      .catch(() => mounted.current && setFailed(true));
  }, [enabled]);

  const setAccount = useCallback(async (projectId: number, employeeId: number, account: number | null) => {
    const updated: Employee = await api.setAccount(employeeId, account);
    if (!mounted.current) return;
    setProjects((current) =>
      current?.map((project) =>
        project.id !== projectId
          ? project
          : { ...project, employees: project.employees.map((employee) => (employee.id === employeeId ? updated : employee)) },
      ) ?? null,
    );
  }, []);

  return { projects, failed, setAccount };
}
