import { useEffect, useRef, type MutableRefObject } from "react";

/** A ref that is true while the component is mounted, to drop async results that arrive after unmount. */
export function useMounted(): MutableRefObject<boolean> {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return mounted;
}
