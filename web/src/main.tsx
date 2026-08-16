import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { registerSW } from "virtual:pwa-register";
import App from "./App";
import "./styles.css";
import "./studio.css";

const desktopWebview = window.location.hostname === "tauri.localhost" || "__TAURI_INTERNALS__" in window;
if (desktopWebview && "serviceWorker" in navigator) {
  void navigator.serviceWorker.getRegistrations().then((registrations) => Promise.all(registrations.map((registration) => registration.unregister())));
} else if (!desktopWebview) {
  registerSW({ immediate: true });
}
createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
