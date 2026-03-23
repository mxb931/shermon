const DOCS = {
  "readme": {
    title: "Project README",
    path: "./docs/README.md",
  },
  "technical-specification": {
    title: "Technical Specification",
    path: "./docs/technical-specification.md",
  },
  "api-developer-usage": {
    title: "API Developer Usage",
    path: "./docs/api/developer-usage.md",
  },
  "api-monitoring-events-v1": {
    title: "Monitoring Events API v1",
    path: "./docs/api/monitoring-events-v1.md",
  },
};

function selectedDocKey() {
  const params = new URLSearchParams(window.location.search);
  return params.get("doc") || "readme";
}

async function loadDocument() {
  const key = selectedDocKey();
  const entry = DOCS[key] || DOCS.readme;

  const titleEl = document.getElementById("docTitle");
  const contentEl = document.getElementById("docContent");
  titleEl.textContent = entry.title;

  try {
    const response = await fetch(entry.path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to load document: HTTP ${response.status}`);
    }
    const text = await response.text();
    contentEl.innerHTML = marked.parse(text);
  } catch (error) {
    contentEl.textContent = String(error);
  }
}

loadDocument();
