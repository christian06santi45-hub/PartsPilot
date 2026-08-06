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

const CSV_COLUMN_ALIASES = {
  part_number: ["part_number", "part-no", "part no", "partno"],
  description: ["description", "current-rpt", "desc"],
  on_hand: ["on_hand", "qoh", "tqty", "tot-stk-qty"],
  on_order: ["on_order", "po-qpr-dr"],
  monthly_demand_avg: ["monthly_demand_avg", "avg-sls"],
  last_sale_days: ["last_sale_days", "age-dr"],
  unit_cost: ["unit_cost", "base-cost"],
  lead_time_days: ["lead_time_days", "lead_time", "lead-time-days"],
  returnable: ["returnable"],
};

function normalizeHeader(name) {
  return String(name || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function getByAliases(row, aliases) {
  for (const alias of aliases) {
    const key = normalizeHeader(alias);
    if (Object.hasOwn(row, key) && String(row[key]).trim() !== "") {
      return String(row[key]).trim();
    }
  }
  return null;
}

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
  const normalizedHeader = header.map((value) => normalizeHeader(value));

  const requiredSourceAliases = {
    part_number: ["part_number", "part-no"],
    on_hand: ["on_hand", "qoh", "tqty", "tot-stk-qty"],
    monthly_demand_avg: ["monthly_demand_avg", "avg-sls", "hist-sum"],
    last_sale_days: ["last_sale_days", "age-dr"],
    unit_cost: ["unit_cost", "base-cost"],
  };

  const missingColumns = Object.entries(requiredSourceAliases)
    .filter(([, aliases]) => aliases.every((alias) => !normalizedHeader.includes(normalizeHeader(alias))))
    .map(([name]) => name);

  if (missingColumns.length > 0) {
    throw new Error(
      `CSV missing required data for: ${missingColumns.join(", ")}. Supported report headers include PART-NO, CURRENT-RPT, QOH, PO-QPR-DR, AVG-SLS, BASE-COST, AGE-DR.`
    );
  }

  return rows.slice(1).map((values, index) => {
    const rowNumber = index + 2;
    const row = Object.fromEntries(
      normalizedHeader.map((column, columnIndex) => [column, (values[columnIndex] || "").trim()])
    );

    const partNumber = getByAliases(row, CSV_COLUMN_ALIASES.part_number);
    const description = getByAliases(row, CSV_COLUMN_ALIASES.description) || "";
    const onHand = getByAliases(row, CSV_COLUMN_ALIASES.on_hand);
    const onOrder = getByAliases(row, CSV_COLUMN_ALIASES.on_order) || "0";

    let monthlyDemand = getByAliases(row, CSV_COLUMN_ALIASES.monthly_demand_avg);
    if (monthlyDemand === null) {
      const histSum = getByAliases(row, ["hist-sum"]);
      if (histSum !== null) {
        monthlyDemand = String(Number(histSum) / 12);
      }
    }

    let lastSaleDays = getByAliases(row, ["last_sale_days"]);
    if (lastSaleDays === null) {
      const ageMonths = getByAliases(row, ["age-dr"]);
      if (ageMonths !== null) {
        lastSaleDays = String(Number(ageMonths) * 30);
      }
    }

    const unitCost = getByAliases(row, CSV_COLUMN_ALIASES.unit_cost);
    const leadTime = getByAliases(row, CSV_COLUMN_ALIASES.lead_time_days) || "7";
    const returnable = getByAliases(row, CSV_COLUMN_ALIASES.returnable) || "true";

    if (partNumber === null || onHand === null || monthlyDemand === null || lastSaleDays === null || unitCost === null) {
      throw new Error(`Missing required values at CSV row ${rowNumber}.`);
    }

    return {
      part_number: partNumber,
      description,
      on_hand: parseRequiredNumber(onHand, "on_hand", rowNumber),
      on_order: parseRequiredNumber(onOrder, "on_order", rowNumber),
      monthly_demand_avg: parseRequiredNumber(monthlyDemand, "monthly_demand_avg", rowNumber),
      last_sale_days: parseRequiredNumber(lastSaleDays, "last_sale_days", rowNumber),
      unit_cost: parseRequiredNumber(unitCost, "unit_cost", rowNumber),
      lead_time_days: parseRequiredNumber(leadTime, "lead_time_days", rowNumber),
      returnable: coerceCsvBoolean(returnable, rowNumber),
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

function numberOrDefault(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function safeDiv(num, den) {
  if (den <= 0) {
    return 0;
  }
  return num / den;
}

function calcTurns(onHand, monthlyDemandAvg) {
  const annualDemand = monthlyDemandAvg * 12;
  const avgInventory = Math.max(onHand / 2, 1);
  return safeDiv(annualDemand, avgInventory);
}

function calcDaysSupply(onHand, monthlyDemandAvg) {
  return safeDiv(onHand, Math.max(monthlyDemandAvg / 30, 0.001));
}

function calcObsolescenceRisk(part) {
  const staleComponent = clamp(part.last_sale_days / 365, 0, 1.5);
  const lowDemandComponent = clamp(1 - safeDiv(part.monthly_demand_avg, 6), 0, 1);
  const stockExcessComponent = clamp(
    safeDiv(part.on_hand, Math.max(part.monthly_demand_avg, 0.25)) / 12,
    0,
    1.5
  );

  const risk = staleComponent * 0.45 + lowDemandComponent * 0.25 + stockExcessComponent * 0.3;
  return clamp(risk, 0, 1);
}

function calcStockoutRisk(part, constraints) {
  const daysSupply = calcDaysSupply(part.on_hand, part.monthly_demand_avg);
  const leadPlusReview = part.lead_time_days + constraints.review_period_days;

  const pressure = safeDiv(leadPlusReview - daysSupply, Math.max(leadPlusReview, 1));
  const baseline = clamp(pressure, 0, 1);

  const serviceBuffer = 1 + Math.max(0, (constraints.min_fill_rate_pct - 94) / 100) * 0.4;
  const adjusted = clamp(baseline * serviceBuffer, 0, 1);

  if (part.monthly_demand_avg <= 0.2) {
    return adjusted * 0.25;
  }
  return adjusted;
}

function calcConfidenceScore(action, obRisk, soRisk, daysSupply, constraints) {
  const separation = Math.abs(obRisk - soRisk);
  let raw = 0.45;

  if (action === "buy") {
    raw = 0.42 + soRisk * 0.45 + (1 - obRisk) * 0.13;
  } else if (action === "liquidate" || action === "return_to_vendor") {
    raw = 0.46 + obRisk * 0.39 + (1 - soRisk) * 0.15;
  } else if (action === "stop_ordering" || action === "transfer") {
    raw = 0.44 + obRisk * 0.31 + (1 - soRisk) * 0.12;
  } else {
    raw = 0.45 + (1 - separation) * 0.2;
  }

  if (["stop_ordering", "transfer", "liquidate", "return_to_vendor"].includes(action)) {
    const threshold = Math.max(constraints.excess_days_supply_threshold, 1);
    raw += clamp((daysSupply - threshold) / threshold, 0, 0.12);
  }

  if (action === "hold" && soRisk >= 0.4) {
    raw += 0.08;
  }

  return clamp(raw, 0.05, 0.99);
}

function recommendForPartLocal(part, constraints) {
  const currentTurns = calcTurns(part.on_hand, part.monthly_demand_avg);
  const obRisk = calcObsolescenceRisk(part);
  const soRisk = calcStockoutRisk(part, constraints);

  let action = "hold";
  let orderQty = 0;
  let rationale = "Balanced profile; maintain current policy.";
  let valueImpact = 0;
  let projectedOnHand = part.on_hand;

  const reductionPressure = clamp(constraints.target_inventory_reduction_pct / 100, 0, 1);
  const maxReductionPct = clamp(constraints.max_single_part_reduction_pct / 100, 0, 1);
  const daysSupply = calcDaysSupply(part.on_hand, part.monthly_demand_avg);
  const highVelocity = part.monthly_demand_avg >= constraints.high_velocity_demand_threshold;
  const freshSales = part.last_sale_days <= 14;
  const emergencyFloor = Math.max(0, constraints.emergency_stock_days);
  const excessDays = daysSupply >= constraints.excess_days_supply_threshold;

  const applyReduction = (rawUnits) => {
    const cappedUnits = Math.min(rawUnits, part.on_hand * maxReductionPct);
    return clamp(cappedUnits, 0, part.on_hand);
  };

  if (highVelocity && freshSales && soRisk >= 0.35) {
    action = "buy";
    const coverageDays = part.lead_time_days + constraints.review_period_days + emergencyFloor;
    const dailyDemand = part.monthly_demand_avg / 30;
    const serviceBias = Math.max(0, (constraints.min_fill_rate_pct - 94) / 100);
    const targetStock = coverageDays * dailyDemand * (1 + serviceBias);
    orderQty = Math.max(targetStock - (part.on_hand + part.on_order), 0);
    projectedOnHand = part.on_hand + orderQty;
    rationale = "Fast-moving part with recent demand and service pressure; protect availability.";
  } else if (obRisk >= 0.75 && soRisk <= 0.2) {
    action = part.returnable ? "return_to_vendor" : "liquidate";
    const reductionUnits = applyReduction(part.on_hand * (0.65 + reductionPressure * 0.2));
    valueImpact = reductionUnits * part.unit_cost;
    projectedOnHand = Math.max(part.on_hand - reductionUnits, 0);
    rationale = "High obsolescence risk with low service risk; remove majority of exposure now.";
  } else if (obRisk >= 0.6 && soRisk <= 0.3) {
    action = "stop_ordering";
    const reductionUnits = applyReduction(part.on_hand * (0.35 + reductionPressure * 0.15));
    valueImpact = reductionUnits * part.unit_cost;
    projectedOnHand = Math.max(part.on_hand - reductionUnits, 0);
    rationale = "Aging inventory with weak demand; stop replenishment and run down stock.";
  } else if (excessDays && part.monthly_demand_avg <= 3 && soRisk <= 0.45) {
    action = "stop_ordering";
    const reductionUnits = applyReduction(part.on_hand * (0.2 + reductionPressure * 0.2));
    valueImpact = reductionUnits * part.unit_cost;
    projectedOnHand = Math.max(part.on_hand - reductionUnits, 0);
    rationale = "Excess days of supply exceeds policy threshold; reduce depth gradually.";
  } else if (soRisk >= 0.65 && obRisk <= 0.55) {
    action = "buy";
    const targetDays = part.lead_time_days + constraints.review_period_days + emergencyFloor;
    const dailyDemand = part.monthly_demand_avg / 30;
    const targetStock = targetDays * dailyDemand;
    const serviceBuffer = 1 + Math.max(0, (constraints.min_fill_rate_pct - 94) / 100) * 1.2;
    orderQty = Math.max(targetStock * serviceBuffer - (part.on_hand + part.on_order), 0);
    projectedOnHand = part.on_hand + orderQty;
    rationale = "High stockout risk; buy enough to protect fill-rate through lead time.";
  } else if (obRisk >= 0.5 && part.returnable) {
    action = "transfer";
    const reductionUnits = applyReduction(part.on_hand * (0.25 + reductionPressure * 0.1));
    valueImpact = reductionUnits * part.unit_cost;
    projectedOnHand = Math.max(part.on_hand - reductionUnits, 0);
    rationale = "Moderate obsolescence risk; transfer excess to higher-demand locations.";
  }

  if (["liquidate", "return_to_vendor", "transfer", "stop_ordering"].includes(action) && soRisk >= 0.4) {
    action = "hold";
    projectedOnHand = part.on_hand;
    valueImpact = 0;
    rationale = "Inventory risk is elevated but service risk is material; avoid depletion action.";
  }

  const projectedTurns = calcTurns(projectedOnHand, part.monthly_demand_avg);
  const confidence = calcConfidenceScore(action, obRisk, soRisk, daysSupply, constraints);

  return {
    part_number: part.part_number,
    description: part.description,
    current_turns: Number(currentTurns.toFixed(2)),
    projected_turns: Number(projectedTurns.toFixed(2)),
    obsolescence_risk: Number(obRisk.toFixed(2)),
    stockout_risk: Number(soRisk.toFixed(2)),
    recommended_action: action,
    recommended_order_qty: Number(orderQty.toFixed(1)),
    confidence_score: Number(confidence.toFixed(2)),
    rationale,
    inventory_value_impact: Number(valueImpact.toFixed(2)),
  };
}

function normalizePartForLocalEngine(part) {
  return {
    part_number: String(part.part_number || "").trim(),
    description: String(part.description || ""),
    on_hand: Math.max(0, numberOrDefault(part.on_hand, 0)),
    on_order: Math.max(0, numberOrDefault(part.on_order, 0)),
    monthly_demand_avg: Math.max(0, numberOrDefault(part.monthly_demand_avg, 0)),
    last_sale_days: Math.max(0, Math.round(numberOrDefault(part.last_sale_days, 0))),
    unit_cost: Math.max(0, numberOrDefault(part.unit_cost, 0)),
    lead_time_days: Math.max(0, Math.round(numberOrDefault(part.lead_time_days, 7))),
    returnable: typeof part.returnable === "boolean" ? part.returnable : String(part.returnable).toLowerCase() !== "false",
  };
}

function buildPlanLocal(parts, constraints) {
  const normalizedParts = parts.map(normalizePartForLocalEngine).filter((part) => part.part_number !== "");
  const recommendations = normalizedParts.map((part) => recommendForPartLocal(part, constraints));

  let currentValue = 0;
  let projectedValue = 0;
  let currentTurnNumerator = 0;
  let projectedTurnNumerator = 0;
  let totalWeight = 0;
  let obsoleteCount = 0;
  let buyCount = 0;

  normalizedParts.forEach((part, index) => {
    const rec = recommendations[index];
    const partValue = part.on_hand * part.unit_cost;
    const projectedOnHandValue = partValue - rec.inventory_value_impact + rec.recommended_order_qty * part.unit_cost;
    const weight = Math.max(partValue, 1);

    currentTurnNumerator += rec.current_turns * weight;
    projectedTurnNumerator += rec.projected_turns * weight;
    totalWeight += weight;

    currentValue += partValue;
    projectedValue += Math.max(projectedOnHandValue, 0);

    if (rec.obsolescence_risk >= 0.6) {
      obsoleteCount += 1;
    }
    if (rec.recommended_action === "buy") {
      buyCount += 1;
    }
  });

  let inventoryReductionPct = 0;
  if (currentValue > 0) {
    inventoryReductionPct = ((currentValue - projectedValue) / currentValue) * 100;
  }

  recommendations.sort((a, b) => {
    const actionRankA = a.recommended_action === "liquidate" ? 0 : 1;
    const actionRankB = b.recommended_action === "liquidate" ? 0 : 1;
    if (actionRankA !== actionRankB) {
      return actionRankA - actionRankB;
    }
    return b.obsolescence_risk - a.obsolescence_risk;
  });

  return {
    summary: {
      current_inventory_value: Number(currentValue.toFixed(2)),
      projected_inventory_value: Number(projectedValue.toFixed(2)),
      inventory_reduction_pct: Number(inventoryReductionPct.toFixed(2)),
      current_weighted_turns: Number(safeDiv(currentTurnNumerator, totalWeight).toFixed(2)),
      projected_weighted_turns: Number(safeDiv(projectedTurnNumerator, totalWeight).toFixed(2)),
      parts_flagged_obsolete: obsoleteCount,
      parts_buy_recommended: buyCount,
    },
    recommendations,
  };
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

  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const responseText = await response.text();
      let message = `Failed to run plan (HTTP ${response.status}).`;

      if (responseText) {
        try {
          const parsed = JSON.parse(responseText);
          if (Array.isArray(parsed.detail) && parsed.detail.length > 0) {
            const first = parsed.detail[0];
            const fieldPath = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "request";
            message = `${fieldPath}: ${first.msg}`;
          } else if (typeof parsed.detail === "string") {
            message = parsed.detail;
          }
        } catch {
          message = `${message} ${responseText.slice(0, 160)}`;
        }
      }

      if (response.status === 405) {
        const localData = buildPlanLocal(payload.parts, payload.constraints);
        recommendationState = localData.recommendations || [];
        activeActionFilter = "all";
        renderKpis(localData.summary);
        renderActionFilter(recommendationState);
        applyRecommendationView();
        setStatus("Plan complete with local fallback engine (API POST /api/plan returned 405).");
        return;
      }

      alert(message);
      setStatus(`Plan failed: ${message}`);
      return;
    }

    const data = await response.json();
    recommendationState = data.recommendations || [];
    activeActionFilter = "all";
    renderKpis(data.summary);
    renderActionFilter(recommendationState);
    applyRecommendationView();
    setStatus(`Plan complete: ${recommendationState.length} recommendations.`);
  } catch (error) {
    try {
      const localData = buildPlanLocal(payload.parts, payload.constraints);
      recommendationState = localData.recommendations || [];
      activeActionFilter = "all";
      renderKpis(localData.summary);
      renderActionFilter(recommendationState);
      applyRecommendationView();
      setStatus("Plan complete with local fallback engine (API unavailable).");
    } catch {
      const message = error instanceof Error ? error.message : "Planner API unreachable.";
      alert(`Failed to run plan: ${message}`);
      setStatus(`Plan failed: ${message}`);
    }
  }
}

function buildPayloadFromScreen(existingParts) {
  const parts = existingParts || JSON.parse(partsJsonEl.value);

  const targetReduction = clamp(numberOrDefault(targetReductionEl.value, 15), 0, 100);
  const minFillRate = clamp(numberOrDefault(minFillRateEl.value, 94), 0, 100);
  const reviewPeriodDays = Math.max(1, Math.round(numberOrDefault(reviewDaysEl.value, 14)));
  const emergencyStockDays = clamp(Math.round(numberOrDefault(emergencyStockDaysEl.value, 3)), 0, 30);
  const maxPartReduction = clamp(numberOrDefault(maxPartReductionEl.value, 70), 0, 100);
  const excessDaysThreshold = clamp(Math.round(numberOrDefault(excessDaysThresholdEl.value, 120)), 30, 720);
  const highVelocityThreshold = clamp(numberOrDefault(highVelocityThresholdEl.value, 12), 1, 100);

  // Mirror normalized values back into the UI so users can see what was sent.
  targetReductionEl.value = String(targetReduction);
  minFillRateEl.value = String(minFillRate);
  reviewDaysEl.value = String(reviewPeriodDays);
  emergencyStockDaysEl.value = String(emergencyStockDays);
  maxPartReductionEl.value = String(maxPartReduction);
  excessDaysThresholdEl.value = String(excessDaysThreshold);
  highVelocityThresholdEl.value = String(highVelocityThreshold);

  return {
    parts,
    constraints: {
      target_inventory_reduction_pct: targetReduction,
      min_fill_rate_pct: minFillRate,
      review_period_days: reviewPeriodDays,
      emergency_stock_days: emergencyStockDays,
      max_single_part_reduction_pct: maxPartReduction,
      excess_days_supply_threshold: excessDaysThreshold,
      high_velocity_demand_threshold: highVelocityThreshold,
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
    let parts = [];
    let usedClientFallback = false;

    try {
      const response = await fetch("/api/parts/import-csv", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ csv_texts: csvTexts }),
      });

      if (!response.ok) {
        const responseText = await response.text();
        let message = "Failed to import CSV files.";

        if (responseText) {
          try {
            const parsed = JSON.parse(responseText);
            message = parsed.detail || message;
          } catch {
            message = `CSV import API failed (${response.status}).`;
          }
        }

        throw new Error(message);
      }

      const data = await response.json();
      parts = data.parts || [];
    } catch (apiError) {
      // Keep import available even when backend import endpoint fails.
      parts = csvTexts.flatMap((csvText) => parsePartsCsv(csvText));
      usedClientFallback = true;
      console.warn("Falling back to client-side CSV parsing:", apiError);
    }

    partsJsonEl.value = JSON.stringify(parts, null, 2);
    setStatus(
      usedClientFallback
        ? `Imported ${parts.length} parts from ${files.length} CSV file${files.length === 1 ? "" : "s"} (client fallback).`
        : `Imported ${parts.length} parts from ${files.length} CSV file${files.length === 1 ? "" : "s"}.`
    );
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
