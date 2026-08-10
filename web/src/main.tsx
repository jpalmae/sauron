import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { BrandingProvider } from "./lib/branding";
import { registerServiceWorker } from "./lib/push";

void registerServiceWorker();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrandingProvider>
      <App />
    </BrandingProvider>
  </StrictMode>,
);
