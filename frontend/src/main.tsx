import "./styles/fonts.css";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/pdf.css";
import "./styles/comparison.css";
import "./styles/card.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { App } from "./App";
import { AuthProvider } from "./auth/AuthContext";
import { initI18n } from "./i18n";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Missing #root element in index.html");
}
const root = rootElement;

initI18n().then(() => {
  createRoot(root).render(
    <StrictMode>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </StrictMode>,
  );
});
