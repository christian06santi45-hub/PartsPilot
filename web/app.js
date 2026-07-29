const loadDemoButton = document.getElementById("load-demo");
const runPlanButton = document.getElementById("run-plan");
const downloadTemplateButton = document.getElementById("download-template");
const exportPlanButton = document.getElementById("export-plan");
const importCsvButton = document.getElementById("import-csv");
const applyPresetButton = document.getElementById("apply-preset");
const csvFileEl = document.getElementById("csv-file");
const partsJsonEl = document.getElementById("parts-json");
const recommendationBody = document.getElementById("recommendation-body");
const kpiGrid = document.getElementById("kpi-grid");
const resultStatusEl = document.getElementById("result-status");
const actionFilterEl = document.getElementById("action-filter");

const targetReductionEl = document.getElementById("target-reduction");
const minFillRateEl = document.getElementById("min-fill-rate");
const reviewDaysEl = document.getElementById("review-days");
const emergencyStockDaysEl = document.getElementById("emergency-stock-days");
const maxPartReductionEl = document.getElementById("max-part-reduction");
const excessDaysThresholdEl = document.getElementById("excess-days-threshold");
const highVelocityThresholdEl = document.getElementById("high-velocity-threshold");
const scenarioPresetEl = document.getElementById("scenario-preset");

let recommendationState = [];
let activeActionFilter = "all";
let activeSort = { key: "confidence_score", direction: "desc" };

const SCENARIO_PRESETS = {
  balanced: {
    target_inventory_reduction_pct: 15,
    min_fill_rate_pct: 94,
    review_period_days: 14,
    emergency_stock_days: 3,
    max_single_part_reduction_pct: 70,
    excess_days_supply_threshold: 120,
    high_velocity_demand_threshold: 12,
  },
  service_first: {
    target_inventory_reduction_pct: 10,
    min_fill_rate_pct: 98,
    review_period_days: 14,
    emergency_stock_days: 7,
    max_single_part_reduction_pct: 50,
    excess_days_supply_threshold: 140,
    high_velocity_demand_threshold: 10,
  },
  aggressive_reduction: {
    target_inventory_reduction_pct: 35,
    min_fill_rate_pct: 93,
    review_period_days: 14,
    emergency_stock_days: 2,
    max_single_part_reduction_pct: 85,
    excess_days_supply_threshold: 90,
    high_velocity_demand_threshold: 14,
  },
};

const CSV_COLUMNS = [
  "part_number",
  "description",
  "on_hand",
  "on_order",
  "monthly_demand_avg",
  "last_sale_days",
  "unit_cost",
  "lead_time_days",
  "returnable",
];

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

function formatAction(action) {
  return action.replaceAll("_", " ");
}

function parseCsvRows(csvText) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;

  for (let index = 0; index < csvText.length; index += 1) {
    const char = csvText[index];

    if (char === '"') {
      if (inQuotes && csvText[index + 1] === '"') {
        field += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (!inQuotes && char === ",") {
      row.push(field);
      field = "";
      continue;
    }

    if (!inQuotes && (char === "\n" || char === "\r")) {
      if (char === "\r" && csvText[index + 1] === "\n") {
        index += 1;
      }

      row.push(field);
      field = "";
      rows.push(row);
      row = [];
      continue;
    }

    field += char;
  }

  if (inQuotes) {
    throw new Error("CSV contains an unclosed quoted field.");
  }

  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }

  return rows.filter((currentRow) => currentRow.some((value) => value.trim() !== ""));
}

function coerceCsvBoolean(value, rowNumber) {
  const normalized = (value || "").trim().toLowerCase();
  if (["true", "1", "yes", "y"].includes(normalized)) {
    return true;
  }
  if (["false", "0", "no", "n"].includes(normalized)) {
    return false;
  }
  throw new Error(`Invalid boolean value at CSV row ${rowNumber}: ${value}`);
}

function parseRequiredNumber(value, fieldName, rowNumber) {
  const parsed = Number(value);
  if (Number.isNaN(parsed)) {
    throw new Error(`Invalid numeric value for ${fieldName} at CSV row ${rowNumber}.`);
  }
  return parsed;
}

function parsePartsCsv(csvText) {
  const rows = parseCsvRows(csvText.replace(/^\ufeff/, ""));
  if (rows.length === 0) {
    throw new Error("CSV appears to be empty.");
  }

  const header = rows[0].map((value) => value.trim());
  const missingColumns = CSV_COLUMNS.filter((column) => !header.includes(column));
  if (missingColumns.length > 0) {
    throw new Error(`CSV missing columns: ${missingColumns.join(", ")}`);
  }

  return rows.slice(1).map((values, index) => {
    const rowNumber = index + 2;
    const row = Object.fromEntries(header.map((column, columnIndex) => [column, values[columnIndex] || ""]));

    return {
      part_number: row.part_number,
      description: row.description,
      on_hand: parseRequiredNumber(row.on_hand, "on_hand", rowNumber),
      on_order: row.on_order === "" ? 0 : parseRequiredNumber(row.on_order, "on_order", rowNumber),
      monthly_demand_avg: parseRequiredNumber(row.monthly_demand_avg, "monthly_demand_avg", rowNumber),
      last_sale_days: parseRequiredNumber(row.last_sale_days, "last_sale_days", rowNumber),
      unit_cost: parseRequiredNumber(row.unit_cost, "unit_cost", rowNumber),
      lead_time_days: parseRequiredNumber(row.lead_time_days, "lead_time_days", rowNumber),
      returnable: coerceCsvBoolean(row.returnable || "true", rowNumber),
    };
  });
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
        <td><span class="badge action-${r.recommended_action}">${formatAction(r.recommended_action)}</span></td>
        <td>${pct((r.confidence_score || 0) * 100)}</td>
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

function renderActionFilter(recommendations) {
  const counts = recommendations.reduce(
    (acc, rec) => {
      acc[rec.recommended_action] = (acc[rec.recommended_action] || 0) + 1;
      return acc;
    },
    { all: recommendations.length }
  );

  const orderedActions = ["all", ...Object.keys(counts).filter((k) => k !== "all").sort()];
  actionFilterEl.innerHTML = orderedActions
    .map((action) => {
      const activeClass = action === activeActionFilter ? "active" : "";
      return `<button class="filter-chip ${activeClass}" data-action-filter="${action}">${formatAction(action)} (${counts[action] || 0})</button>`;
    })
    .join("");

  actionFilterEl.querySelectorAll("[data-action-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      activeActionFilter = button.getAttribute("data-action-filter") || "all";
      applyRecommendationView();
    });
  });
}

function compareValues(a, b, sortKey) {
  const aValue = a[sortKey];
  const bValue = b[sortKey];

  if (typeof aValue === "number" && typeof bValue === "number") {
    return aValue - bValue;
  }
  return String(aValue).localeCompare(String(bValue));
}

function applyRecommendationView() {
  const filtered =
    activeActionFilter === "all"
      ? [...recommendationState]
      : recommendationState.filter((r) => r.recommended_action === activeActionFilter);

  const direction = activeSort.direction === "asc" ? 1 : -1;
  filtered.sort((a, b) => compareValues(a, b, activeSort.key) * direction);
  renderRecommendations(filtered);
}

function wireTableSorting() {
  document.querySelectorAll("th[data-sort-key]").forEach((header) => {
    header.addEventListener("click", () => {
      const key = header.getAttribute("data-sort-key");
      if (!key) {
        return;
      }

      if (activeSort.key === key) {
        activeSort.direction = activeSort.direction === "asc" ? "desc" : "asc";
      } else {
        activeSort = { key, direction: "desc" };
      }

      applyRecommendationView();
    });
  });
}

function setStatus(message) {
  resultStatusEl.textContent = message;
}

function applyPresetValues(presetKey) {
  const preset = SCENARIO_PRESETS[presetKey];
  if (!preset) {
    return;
  }

  targetReductionEl.value = preset.target_inventory_reduction_pct;
  minFillRateEl.value = preset.min_fill_rate_pct;
  reviewDaysEl.value = preset.review_period_days;
  emergencyStockDaysEl.value = preset.emergency_stock_days;
  maxPartReductionEl.value = preset.max_single_part_reduction_pct;
  excessDaysThresholdEl.value = preset.excess_days_supply_threshold;
  highVelocityThresholdEl.value = preset.high_velocity_demand_threshold;
  setStatus(`Preset applied: ${formatAction(presetKey)}.`);
}

async function loadDemo() {
  const response = await fetch("/api/demo-data");
  const data = await response.json();

  partsJsonEl.value = JSON.stringify(data.parts, null, 2);
  targetReductionEl.value = data.constraints.target_inventory_reduction_pct;
  minFillRateEl.value = data.constraints.min_fill_rate_pct;
  reviewDaysEl.value = data.constraints.review_period_days;
  emergencyStockDaysEl.value = data.constraints.emergency_stock_days ?? 3;
  maxPartReductionEl.value = data.constraints.max_single_part_reduction_pct ?? 70;
  excessDaysThresholdEl.value = data.constraints.excess_days_supply_threshold ?? 120;
  highVelocityThresholdEl.value = data.constraints.high_velocity_demand_threshold ?? 12;
  scenarioPresetEl.value = "balanced";
  setStatus("Demo data loaded. Tune constraints and run the plan.");
}

async function runPlan() {
  recommendationBody.innerHTML = "";
  setStatus("Running planner...");

  let parts;
  try {
    parts = JSON.parse(partsJsonEl.value);
  } catch {
    alert("Parts JSON is invalid. Please fix formatting.");
    return;
  }

  const payload = buildPayloadFromScreen(parts);

  const response = await fetch("/api/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    alert("Failed to run plan.");
    setStatus("Plan failed. Check inputs and try again.");
    return;
  }

  const data = await response.json();
  recommendationState = data.recommendations || [];
  activeActionFilter = "all";
  renderKpis(data.summary);
  renderActionFilter(recommendationState);
  applyRecommendationView();
  setStatus(`Plan complete: ${recommendationState.length} recommendations.`);
}

function buildPayloadFromScreen(existingParts) {
  const parts = existingParts || JSON.parse(partsJsonEl.value);
  return {
    parts,
    constraints: {
      target_inventory_reduction_pct: Number(targetReductionEl.value),
      min_fill_rate_pct: Number(minFillRateEl.value),
      review_period_days: Number(reviewDaysEl.value),
      emergency_stock_days: Number(emergencyStockDaysEl.value),
      max_single_part_reduction_pct: Number(maxPartReductionEl.value),
      excess_days_supply_threshold: Number(excessDaysThresholdEl.value),
      high_velocity_demand_threshold: Number(highVelocityThresholdEl.value),
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
  const files = Array.from(csvFileEl.files || []);
  if (files.length === 0) {
    alert("Choose at least one CSV file.");
    return;
  }

  try {
    const csvTexts = await Promise.all(files.map((file) => file.text()));
    const importPayload = { csv_texts: csvTexts };
    const response = await fetch("/api/parts/import-csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(importPayload),
    });

    if (!response.ok) {
      const errorBody = await response.json().catch(() => ({}));
      throw new Error(errorBody.detail || "Failed to import CSV files.");
    }

    const data = await response.json();
    const parts = data.parts || [];
    partsJsonEl.value = JSON.stringify(parts, null, 2);
    setStatus(`Imported ${parts.length} parts from ${files.length} CSV file${files.length === 1 ? "" : "s"}.`);
  } catch (error) {
    const message = error instanceof Error ? error.message : "Failed to import CSV.";
    alert(message);
    return;
  }
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
applyPresetButton.addEventListener("click", () => applyPresetValues(scenarioPresetEl.value));
wireTableSorting();

loadDemo();
