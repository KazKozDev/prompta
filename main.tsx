import React from "react";
import ReactDOM from "react-dom/client";
import App from "./index.tsx";

const root = document.getElementById("app");
if (root) {
  ReactDOM.createRoot(root).render(<App />);
} else {
  const newRoot = document.createElement("div");
  newRoot.id = "app";
  document.body.appendChild(newRoot);
  ReactDOM.createRoot(newRoot).render(<App />);
}
