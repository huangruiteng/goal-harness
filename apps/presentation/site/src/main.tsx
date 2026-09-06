import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { SweMarathonBrief } from "./SweMarathonBrief";
import "./styles.css";
import "./swe-marathon-brief.css";

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("LoopX homepage root is missing");

const pathSegments = window.location.pathname.split("/").filter(Boolean);
const isSweMarathonBrief = pathSegments.slice(-2).join("/") === "benchmarks/swe-marathon";

createRoot(rootElement).render(
  <StrictMode>{isSweMarathonBrief ? <SweMarathonBrief /> : <App />}</StrictMode>,
);
