import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import App from "./App";
import "./styles.css";

const SCROLLBAR_IDLE_TIMEOUT_MS = 900;
const scrollbarHideTimers = new WeakMap<Element, number>();

function markScrollbarActive(event: Event) {
  const target = event.target instanceof Element ? event.target : document.documentElement;
  target.classList.add("scrollbar-active");

  const pendingTimer = scrollbarHideTimers.get(target);
  if (pendingTimer !== undefined) window.clearTimeout(pendingTimer);

  const timer = window.setTimeout(() => {
    target.classList.remove("scrollbar-active");
    scrollbarHideTimers.delete(target);
  }, SCROLLBAR_IDLE_TIMEOUT_MS);
  scrollbarHideTimers.set(target, timer);
}

document.addEventListener("scroll", markScrollbarActive, { capture: true, passive: true });

createRoot(document.getElementById("root") as HTMLElement).render(
  <StrictMode>
    <App />
    <Toaster position="top-right" richColors />
  </StrictMode>,
);
