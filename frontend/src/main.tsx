import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Mobile browsers can leave the page scrolled up after the virtual keyboard closes
// or the app returns from the background; put the document back at the origin.
function resetScroll() {
  if (window.scrollX !== 0 || window.scrollY !== 0) window.scrollTo(0, 0);
}

document.addEventListener("focusout", () => setTimeout(resetScroll, 100));
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") resetScroll();
});
window.addEventListener("pageshow", resetScroll);
window.visualViewport?.addEventListener("resize", () => {
  if (window.visualViewport && window.visualViewport.height >= window.innerHeight - 1) resetScroll();
});
