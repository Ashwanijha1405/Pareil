// The one place the frontend learns where the live API is.
// Local dev: the backend on port 8000 (frontend may be served from any other port).
// Production: the Render service. Demos never call it; only "Run live" and CSV uploads do.
window.PAREIL_API = ["localhost", "127.0.0.1"].includes(location.hostname)
  ? `http://${location.hostname}:8000`
  : "https://REPLACE-WITH-RENDER-SERVICE.onrender.com";
