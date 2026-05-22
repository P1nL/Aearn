import { useCallback, useEffect, useRef, useState } from "react";

type AutoSaveStatus = "idle" | "saving" | "saved" | "error";

type UseAutoSaveOptions = {
  delay?: number;
  enabled?: boolean;
};

type UseAutoSaveReturn = {
  status: AutoSaveStatus;
  flush: () => Promise<boolean>;
};

export function useAutoSave(
  value: string,
  onSave: (value: string) => Promise<boolean>,
  options: UseAutoSaveOptions = {},
): UseAutoSaveReturn {
  const { delay = 800, enabled = true } = options;
  const [status, setStatus] = useState<AutoSaveStatus>("idle");
  const timeoutRef = useRef<number | undefined>(undefined);
  const isSavingRef = useRef(false);
  const lastSavedRef = useRef(value);
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;

  const pendingValueRef = useRef(value);
  pendingValueRef.current = value;

  const doSave = useCallback(async (val: string): Promise<boolean> => {
    if (isSavingRef.current) {
      return false;
    }
    if (val === lastSavedRef.current) {
      return true;
    }
    isSavingRef.current = true;
    setStatus("saving");
    try {
      const success = await onSaveRef.current(val);
      if (success) {
        lastSavedRef.current = val;
        setStatus("saved");
      } else {
        setStatus("error");
      }
      return success;
    } catch {
      setStatus("error");
      return false;
    } finally {
      isSavingRef.current = false;
    }
  }, []);

  useEffect(() => {
    if (!enabled) {
      return;
    }
    if (value === lastSavedRef.current) {
      return;
    }
    setStatus("idle");
    window.clearTimeout(timeoutRef.current);
    timeoutRef.current = window.setTimeout(() => {
      void doSave(value);
    }, delay);
    return () => window.clearTimeout(timeoutRef.current);
  }, [value, enabled, delay, doSave]);

  const flush = useCallback(async (): Promise<boolean> => {
    window.clearTimeout(timeoutRef.current);
    const current = pendingValueRef.current;
    if (current === lastSavedRef.current) {
      return true;
    }
    return doSave(current);
  }, [doSave]);

  return { status, flush };
}
