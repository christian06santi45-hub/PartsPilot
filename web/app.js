const loadDemoButton = document.getElementById("load-demo");
const runPlanButton = document.getElementById("run-plan");
const downloadTemplateButton = document.getElementById("download-template");
const exportPlanButton = document.getElementById("export-plan");
const importCsvButton = document.getElementById("import-csv");
const csvFileEl = document.getElementById("csv-file");
const partsJsonEl = document.getElementById("parts-json");
const recommendationBody = document.getElementById("recommendation-body");
const kpiGrid = document.getElementById("kpi-grid");

const targetReductionEl = document.getElementById("target-reduction");
const minFillRateEl = document.getElementById("min-fill-rate");
const reviewDaysEl = document.getElementById("review-days");

function currency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value || 0);
}

function pct(value) {
  return `${(value || 0).toFixed(2)}%`;
}

function renderKpis(summary) {
  const cards = [
    ["Current Inventory", currency(summary.current_inventory_value)],
    ["Projected Inventory", currency(summary.projected_inventory_value)],
    ["Inventory Reduction", pct(summary.inventory_reduction_pct)],
    ["Current Weighted Turns", summary.current_weighted_turns.toFixed(2)],
    ["Projected Weighted Turns", summary.projected_weighted_turns.toFixed(2)],
    ["Obsolete-Flagged Parts", String(summary.parts_flagged_obsolete)],
    ["Buy Recommendations", String(summary.parts_buy_recommended)],
  ];

  kpiGrid.innerHTML = cards
    .map(
      ([label, value]) =>
        `<article class="kpi-card"><h3>${label}</h3><p>${value}</p></article>`
    )
    .join("");
}

function renderRecommendations(recommendations) {
  recommendationBody.innerHTML = recommendations
    .map(
      (r) => `
      <tr>
        <td><strong>${r.part_number}</strong><br/><small>${r.description}</small></td>
        <td><span class="badge action-${r.recommended_action}">${r.recommended_action}</span></td>
        <td>${pct(r.obsolescence_risk * 100)}</td>
        <td>${pct(r.stockout_risk * 100)}</td>
        <td>${r.current_turns.toFixed(2)}</td>
        <td>${r.projected_turns.toFixed(2)}</td>
        <td>${r.recommended_order_qty.toFixed(1)}</td>
        <td>${currency(r.inventory_value_impact)}</td>
        <td>${r.rationale}</td>
      </tr>
    `
    )
    .join("");
}

async function loadDemo() {
  const response = await fetch("/api/demo-data");
  const data = await response.json();

  partsJsonEl.value = JSON.stringify(data.parts, null, 2);
  targetReductionEl.value = data.constraints.target_inventory_reduction_pct;
  minFillRateEl.value = data.constraints.min_fill_rate_pct;
  reviewDaysEl.value = data.constraints.review_period_days;
}

async function runPlan() {
  recommendationBody.innerHTML = "";

  let parts;
  try {
    parts = JSON.parse(partsJsonEl.value);
  } catch {
    alert("Parts JSON is invalid. Please fix formatting.");
    return;
  }

  const payload = {
    parts,
    constraints: {
      target_inventory_reduction_pct: Number(targetReductionEl.value),
      min_fill_rate_pct: Number(minFillRateEl.value),
      review_period_days: Number(reviewDaysEl.value),
    },
  };

  const response = await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    alert("Failed to run plan.");
    return;
  }

  const data = await response.json();
  renderKpis(data.summary);
  renderRecommendations(data.recommendations);
}

function buildPayloadFromScreen() {
  const parts = JSON.parse(partsJsonEl.value);
  return {
    parts,
    constraints: {
      target_inventory_reduction_pct: Number(targetReductionEl.value),
      min_fill_rate_pct: Number(minFillRateEl.value),
      review_period_days: Number(reviewDaysEl.value),
    },
  };
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

async function downloadTemplate() {
  const response = await fetch("/api/csv-template");
  if (!response.ok) {
    alert("Failed to download CSV template.");
    return;
  }

  const blob = await response.blob();
  downloadBlob(blob, "partspilot_template.csv");
}

async function importCsv() {
  const file = csvFileEl.files[0];
  if (!file) {
    alert("Choose a CSV file first.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch("/api/parts/import-csv", {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    alert(err.detail || "Failed to import CSV.");
    return;
  }

  const data = await response.json();
  partsJsonEl.value = JSON.stringify(data.parts, null, 2);
}

async function exportPlanCsv() {
  let payload;
  try {
    payload = buildPayloadFromScreen();
  } catch {
    alert("Parts JSON is invalid. Fix it before export.");
    return;
  }

  const response = await fetch("/api/plan/export-csv", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    alert("Failed to export plan CSV.");
    return;
  }

  const blob = await response.blob();
  downloadBlob(blob, "partspilot_plan.csv");
}

loadDemoButton.addEventListener("click", loadDemo);
runPlanButton.addEventListener("click", runPlan);
downloadTemplateButton.addEventListener("click", downloadTemplate);
importCsvButton.addEventListener("click", importCsv);
exportPlanButton.addEventListener("click", exportPlanCsv);

loadDemo();
