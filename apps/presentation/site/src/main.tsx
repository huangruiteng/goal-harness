import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles.css";

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("LoopX homepage root is missing");

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
