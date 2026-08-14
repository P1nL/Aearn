import { Toaster, toast } from "sonner";
import type { ExternalToast, ToasterProps } from "sonner";
import styles from "./AearnToast.module.css";

export interface AearnToastOptions {
  kind?: "info" | "success" | "warning" | "error";
  title: string;
  description?: string;
  options?: ExternalToast;
}

export function showAearnToast({ kind = "info", title, description, options }: AearnToastOptions): string | number {
  const payload: ExternalToast = { ...options, description };
  switch (kind) {
    case "success":
      return toast.success(title, payload);
    case "warning":
      return toast.warning(title, payload);
    case "error":
      return toast.error(title, payload);
    case "info":
      return toast(title, payload);
  }
}

export function AearnToast(props: Omit<ToasterProps, "toastOptions">) {
  return (
    <Toaster
      position="top-right"
      closeButton
      {...props}
      toastOptions={{
        classNames: {
          toast: styles.toast,
          title: styles.title,
          description: styles.description,
          actionButton: styles.action,
          cancelButton: styles.cancel,
          closeButton: styles.close,
          success: styles.success,
          warning: styles.warning,
          error: styles.error,
          info: styles.info,
        },
      }}
    />
  );
}
