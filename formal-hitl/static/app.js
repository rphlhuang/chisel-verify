// No build step, no framework: this talks to the FastAPI backend in
// app.py and renders the property table + counterexample waveform panel.
// The verdict column is the engine's word; the "adjudication" column is
// the human's word. Nothing in this file decides correctness -- it only
// presents what the backend already decided and collects the human call.

let currentRunId = null;
let pollTimer = null;
let currentProperties = [];

async function loadVariants() {
  const res = await fetch("/api/variants");
  const data = await res.json();
  const select = document.getElementById("variant-select");
  select.innerHTML = "";
  for (const v of data.variants) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  }
}

function verdictClass(verdict) {
  return `verdict verdict-${verdict}`;
}

function rowClass(verdict) {
  if (verdict === "FAILED") return "row-failed";
  if (verdict === "ERROR") return "row-error";
  return "";
}

function renderTable(properties) {
  currentProperties = properties;
  const tbody = document.getElementById("property-table-body");
  tbody.innerHTML = "";
  for (const p of properties) {
    const tr = document.createElement("tr");
    tr.className = rowClass(p.verdict);
    const svaText = p.antecedent
      ? `if (${p.antecedent})\n  assert (${p.consequent});`
      : `assert (${p.consequent});`;
    const adjText = p.adjudication ? p.adjudication.decision : "";
    tr.innerHTML = `
      <td>${p.name}</td>
      <td>${p.intent}</td>
      <td class="sva">${svaText}</td>
      <td><span class="${verdictClass(p.verdict)}">${p.verdict}</span></td>
      <td>${adjText}</td>
    `;
    if (p.verdict === "FAILED" && p.cex) {
      tr.addEventListener("click", () => showCex(p));
    }
    tbody.appendChild(tr);
  }
}

function showCex(prop) {
  const panel = document.getElementById("cex-panel");
  panel.classList.remove("hidden");
  document.getElementById("cex-title").textContent = `Counterexample: ${prop.name}`;
  const c = prop.cex;
  document.getElementById("cex-summary").textContent =
    `intent: ${prop.intent}\n` +
    `a = ${c.a}\nb = ${c.b}\n` +
    `observed s = ${c.observed_s}\nexpected s = ${c.expected_s}\n` +
    `(fails at BMC step ${c.fail_step})`;

  const waveDiv = document.getElementById("cex-wave");
  waveDiv.innerHTML = '<script type="WaveDrom" id="wavedrom-src"></script><div id="wavedrom-svg"></div>';
  document.getElementById("wavedrom-src").textContent = JSON.stringify(c.wavedrom);
  // WaveDrom's ProcessAll scans <script type="WaveDrom"> tags in the DOM.
  setTimeout(() => {
    if (window.WaveDrom) {
      window.WaveDrom.ProcessAll();
    }
  }, 0);

  panel.dataset.propertyName = prop.name;
}

async function submitAdjudication(decision) {
  const panel = document.getElementById("cex-panel");
  const propertyName = panel.dataset.propertyName;
  if (!propertyName || !currentRunId) return;
  const note = document.getElementById("adjudicate-note").value;

  await fetch(`/api/runs/${currentRunId}/adjudicate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      adjudications: [{ property_name: propertyName, decision, note: note || null }],
    }),
  });

  panel.classList.add("hidden");
  document.getElementById("adjudicate-note").value = "";
  startPolling();
}

async function pollRun() {
  if (!currentRunId) return;
  const res = await fetch(`/api/runs/${currentRunId}`);
  const data = await res.json();
  document.getElementById("status-line").textContent =
    `stage: ${data.stage}  cycle: ${data.cycle}` + (data.error ? `  ERROR: ${data.error}` : "");
  renderTable(data.properties);

  if (data.stage === "done" || data.stage === "error") {
    stopPolling();
    loadTranscript();
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(pollRun, 1000);
  pollRun();
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function loadTranscript() {
  if (!currentRunId) return;
  const res = await fetch(`/api/runs/${currentRunId}/transcript`);
  const data = await res.json();
  document.getElementById("transcript-log").textContent = JSON.stringify(data.events, null, 2);
}

async function startRun() {
  const variant = document.getElementById("variant-select").value;
  const width = parseInt(document.getElementById("width-input").value, 10);
  document.getElementById("cex-panel").classList.add("hidden");

  const res = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ variant, width }),
  });
  if (!res.ok) {
    const err = await res.json();
    document.getElementById("status-line").textContent = `error: ${err.detail}`;
    return;
  }
  const data = await res.json();
  currentRunId = data.run_id;
  startPolling();
}

document.getElementById("run-button").addEventListener("click", startRun);
document.querySelectorAll("#adjudicate-controls button[data-decision]").forEach((btn) => {
  btn.addEventListener("click", () => submitAdjudication(btn.dataset.decision));
});

loadVariants();
