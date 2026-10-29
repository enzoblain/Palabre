import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// The root is fixed and sized to the visible viewport, so the virtual keyboard only
// shrinks the app instead of scrolling the page. iOS may still scroll the document
// to reveal a focused field: undo it and follow visualViewport.height.
function syncViewport() {
  const vv = window.visualViewport;
  if (vv) document.documentElement.style.setProperty("--app-height", `${vv.height}px`);
  if (window.scrollX !== 0 || window.scrollY !== 0) window.scrollTo(0, 0);
}

syncViewport();
window.visualViewport?.addEventListener("resize", syncViewport);
window.visualViewport?.addEventListener("scroll", syncViewport);
window.addEventListener("scroll", syncViewport);
window.addEventListener("pageshow", syncViewport);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") syncViewport();
});
