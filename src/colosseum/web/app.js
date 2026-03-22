/* ══════════════════════════════════════════════
   COLOSSEUM — Arena UI (ES5-compatible)
   ══════════════════════════════════════════════ */

/* ── Gladiator definitions ── */
var GLADIATORS = [
  // ─── Paid models (API / CLI subscription) ───
  {
    id: "claude", name: "Claude", icon: "\u2694\uFE0F", tier: "paid",
    desc: "claude -p --model <model>",
    variants: [
      { model: "claude-opus-4-6", label: "Opus 4.6", type: "claude_cli" },
      { model: "claude-sonnet-4-6", label: "Sonnet 4.6", type: "claude_cli" },
      { model: "claude-haiku-4-5-20251001", label: "Haiku 4.5", type: "claude_cli" }
    ]
  },
  {
    id: "openai", name: "OpenAI", icon: "\uD83D\uDEE1\uFE0F", tier: "paid",
    desc: "codex --model <model> -p",
    variants: [
      { model: "gpt-5.4", label: "GPT-5.4", type: "codex_cli" },
      { model: "gpt-5.3-codex", label: "GPT-5.3 Codex", type: "codex_cli" },
      { model: "o3", label: "o3 (legacy)", type: "codex_cli" },
      { model: "o4-mini", label: "o4-mini (legacy)", type: "codex_cli" }
    ]
  },
  {
    id: "gemini", name: "Gemini", icon: "\uD83D\uDD31", tier: "paid",
    desc: "gemini --model <model> -p",
    variants: [
      { model: "gemini-3.1-pro-preview", label: "3.1 Pro", type: "gemini_cli" },
      { model: "gemini-3-flash-preview", label: "3 Flash", type: "gemini_cli" },
      { model: "gemini-3.1-flash-lite-preview", label: "3.1 Flash Lite", type: "gemini_cli" },
      { model: "gemini-2.5-pro", label: "2.5 Pro", type: "gemini_cli" },
      { model: "gemini-2.5-flash", label: "2.5 Flash", type: "gemini_cli" },
      { model: "gemini-2.5-flash-lite", label: "2.5 Flash Lite", type: "gemini_cli" }
    ]
  },
  // ─── Free / Local models (Ollama) ───
  {
    id: "llama", name: "Llama", icon: "\uD83E\uDD99", tier: "free",
    desc: "ollama run <model>",
    variants: [
      { model: "ollama:llama3.3", label: "Llama 3.3 70B", type: "huggingface_local" },
      { model: "ollama:llama3.2", label: "Llama 3.2 3B", type: "huggingface_local" },
      { model: "ollama:llama3.1", label: "Llama 3.1 8B", type: "huggingface_local" },
      { model: "ollama:llama3.1:70b", label: "Llama 3.1 70B", type: "huggingface_local" }
    ]
  },
  {
    id: "mistral", name: "Mistral", icon: "\uD83C\uDF2A\uFE0F", tier: "free",
    desc: "ollama run <model>",
    variants: [
      { model: "ollama:mistral", label: "Mistral 7B", type: "huggingface_local" },
      { model: "ollama:mixtral", label: "Mixtral 8x7B", type: "huggingface_local" },
      { model: "ollama:mistral-nemo", label: "Nemo 12B", type: "huggingface_local" },
      { model: "ollama:mistral-small", label: "Small 22B", type: "huggingface_local" }
    ]
  },
  {
    id: "qwen", name: "Qwen", icon: "\uD83C\uDFEF", tier: "free",
    desc: "ollama run <model>",
    variants: [
      { model: "ollama:qwen2.5", label: "Qwen 2.5 7B", type: "huggingface_local" },
      { model: "ollama:qwen2.5:14b", label: "Qwen 2.5 14B", type: "huggingface_local" },
      { model: "ollama:qwen2.5:32b", label: "Qwen 2.5 32B", type: "huggingface_local" },
      { model: "ollama:qwen2.5-coder", label: "Coder 7B", type: "huggingface_local" }
    ]
  },
  {
    id: "gemma", name: "Gemma", icon: "\uD83D\uDC8E", tier: "free",
    desc: "ollama run <model>",
    variants: [
      { model: "ollama:gemma3", label: "Gemma 3 4B", type: "huggingface_local" },
      { model: "ollama:gemma3:12b", label: "Gemma 3 12B", type: "huggingface_local" },
      { model: "ollama:gemma3:27b", label: "Gemma 3 27B", type: "huggingface_local" }
    ]
  },
  {
    id: "phi", name: "Phi", icon: "\uD83E\uDDE0", tier: "free",
    desc: "ollama run <model>",
    variants: [
      { model: "ollama:phi4", label: "Phi-4 14B", type: "huggingface_local" },
      { model: "ollama:phi4-mini", label: "Phi-4 Mini", type: "huggingface_local" }
    ]
  },
  {
    id: "deepseek", name: "DeepSeek", icon: "\uD83D\uDD2D", tier: "free",
    desc: "ollama run <model>",
    variants: [
      { model: "ollama:deepseek-r1", label: "R1 7B", type: "huggingface_local" },
      { model: "ollama:deepseek-r1:14b", label: "R1 14B", type: "huggingface_local" },
      { model: "ollama:deepseek-r1:32b", label: "R1 32B", type: "huggingface_local" },
      { model: "ollama:deepseek-v3", label: "V3", type: "huggingface_local" }
    ]
  },
];

/* ── State ── */
var selectedGladiators = {}; // id -> true
var gladiatorVariants = {};  // id -> variant index
var attachedFiles = [];
var MAX_TEXT_FILE_BYTES = 100000;
var MAX_IMAGE_FILE_BYTES = 4 * 1024 * 1024;
var currentRunId = null;
var currentMode = "live"; // "live" or "result"
var encourageInternetSearch = loadBooleanSetting("colosseum:encourage_search", true);
var useEvidenceBasedJudging = loadBooleanSetting("colosseum:evidence_judging", true);
var currentJudgeMode = "automated"; // "automated", "ai", or "human"
var judgeModelIndex = {};

function loadCustomModels() {
  try {
    return JSON.parse(localStorage.getItem("colosseum:custom_models") || "[]").map(normalizeCustomModel);
  }
  catch (e) { return []; }
}
function saveCustomModels(list) {
  localStorage.setItem("colosseum:custom_models", JSON.stringify(list.map(normalizeCustomModel)));
}
function loadBooleanSetting(key, fallback) {
  try {
    var raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    return raw === "true";
  }
  catch (e) { return fallback; }
}

function saveBooleanSetting(key, value) {
  try {
    localStorage.setItem(key, value ? "true" : "false");
  }
  catch (e) { /* ignore */ }
}

var customModels = loadCustomModels();

var gladiatorPersonas = {};  // id -> {persona_id, persona_name, persona_content}
var availablePersonas = [];  // fetched from /personas
var personaBuilderTarget = null;
function normalizeCustomModel(raw) {
  raw = raw || {};
  var safeName = raw.name || "Custom Model";
  var safeId = raw.id || ("custom-" + safeName.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, ""));
  var tier = raw.tier === "paid" ? "paid" : "free";
  var type = raw.type || "command";
  var modelId = raw.model || raw.model_id || safeName;
  return {
    id: safeId || "custom-model",
    name: safeName,
    desc: raw.desc || raw.description || (type === "command" ? (raw.command && raw.command[0]) || "custom command" : modelId),
    type: type,
    tier: tier,
    model: modelId,
    command: Array.isArray(raw.command) ? raw.command : (typeof raw.command === "string" ? raw.command.split(" ").filter(Boolean) : [])
  };
}

// ── Dynamic model discovery ──
// Provider grouping config: maps API type to GLADIATORS entry info
var PROVIDER_GROUP_MAP = {
  "claude_cli": { group: "claude", name: "Claude", icon: "\u2694\uFE0F", tier: "paid", desc: "claude -p --model <model>" },
  "codex_cli":  { group: "openai", name: "OpenAI", icon: "\uD83D\uDEE1\uFE0F", tier: "paid", desc: "codex --model <model> -p" },
  "gemini_cli": { group: "gemini", name: "Gemini", icon: "\uD83D\uDD31", tier: "paid", desc: "gemini --model <model> -p" },
  "ollama":     { group: "ollama", name: "Ollama", icon: "\uD83E\uDD99", tier: "free", desc: "ollama run <model>" },
};

// Maps gladiator group id → CLI tool name (for auth API calls)
var CLI_GROUP_TOOL_MAP = {
  "claude": "claude",
  "openai": "codex",
  "gemini": "gemini",
  "ollama": "ollama",
};

// CLI auth states fetched from /setup/status, keyed by group id
var cliAuthStates = {};
var localRuntimeState = null;
var localRuntimeLoading = false;
var fitResultCache = {};       // normalizedModel → LocalModelFitResult
var fitResultPending = {};     // normalizedModel → true (in-flight)
var gladiatorGpuAssignment = {}; // gid → [gpuIndex, ...] | null (null = runtime default)

function isLocalModelType(type) {
  return type === "ollama" || type === "huggingface_local";
}

function normalizeLocalModelId(rawModel) {
  return String(rawModel || "")
    .replace(/^ollama:/, "")
    .replace(/^hf:/, "")
    .replace(/^huggingface:/, "")
    .trim();
}

function isLocalModelInstalled(modelId) {
  if (!localRuntimeState || !localRuntimeState.installed_models_known) return false;
  var normalized = normalizeLocalModelId(modelId);
  if (!normalized) return false;
  return (localRuntimeState.installed_models || []).some(function(installed) {
    var cleanInstalled = normalizeLocalModelId(installed).replace(/:latest$/, "");
    var cleanNormalized = normalized.replace(/:latest$/, "");
    return installed === normalized ||
      installed === normalized + ":latest" ||
      cleanInstalled === cleanNormalized;
  });
}


var FIT_ICONS   = { perfect: "✅", good: "✓", marginal: "⚠️", too_tight: "❌", unknown: "−" };
var FIT_CLASSES = { perfect: "badge-green", good: "badge-green", marginal: "badge-yellow", too_tight: "badge-red", unknown: "badge-gray" };

function applyFitResultToBadge(badgeEl, result) {
  var memLabel = result.memory_required_gb ? " (" + result.memory_required_gb.toFixed(1) + " GB)" : "";
  badgeEl.textContent = (FIT_ICONS[result.fit_level] || "−") + " " + result.message + memLabel;
  badgeEl.className = badgeEl.className.replace(/badge-\S+/g, "").trim();
  badgeEl.classList.add(FIT_CLASSES[result.fit_level] || "badge-gray");
  badgeEl.classList.remove("hidden");
}

// Render per-card GPU selector for a given gladiator card
function renderCardGpuSelector(gid, cardEl, fitResult) {
  var selectorEl = cardEl ? cardEl.querySelector(".card-gpu-selector") : null;
  if (!selectorEl) return;
  var devices = (localRuntimeState && localRuntimeState.gpu_devices) || [];
  if (!devices.length) { selectorEl.innerHTML = ""; return; }

  var assigned = gladiatorGpuAssignment[gid] || null; // null = runtime default
  var memNeededGb = fitResult && fitResult.memory_required_gb;

  var html = '<div class="card-gpu-label">GPU</div>';
  html += '<div class="card-gpu-options">';
  html += '<label class="card-gpu-opt"><input type="radio" name="gpu-' + esc(gid) + '" value="auto"' + (!assigned ? ' checked' : '') + '> Auto</label>';
  devices.forEach(function(dev) {
    var vramGb = dev.memory_total_mb ? (dev.memory_total_mb / 1024).toFixed(0) : "?";
    var isChecked = assigned && assigned.length === 1 && assigned[0] === dev.index;
    html += '<label class="card-gpu-opt"><input type="radio" name="gpu-' + esc(gid) + '" value="' + dev.index + '"' + (isChecked ? ' checked' : '') + '> GPU ' + dev.index + ' <span class="card-gpu-vram">' + vramGb + 'GB</span></label>';
  });
  if (devices.length > 1) {
    var isAllChecked = assigned && assigned.length === devices.length;
    html += '<label class="card-gpu-opt"><input type="radio" name="gpu-' + esc(gid) + '" value="all"' + (isAllChecked ? ' checked' : '') + '> All (' + devices.length + ')</label>';
  }
  html += '</div>';

  // VRAM feasibility warning
  if (memNeededGb && assigned !== null) {
    var warning = checkGpuVramFeasibility(gid, assigned, memNeededGb, devices);
    if (warning) html += '<div class="card-gpu-warning">' + esc(warning) + '</div>';
  }

  selectorEl.innerHTML = html;

  // Event: radio change → update assignment
  selectorEl.querySelectorAll('input[type="radio"]').forEach(function(radio) {
    radio.addEventListener("change", function() {
      var val = radio.value;
      if (val === "auto") {
        gladiatorGpuAssignment[gid] = null;
      } else if (val === "all") {
        gladiatorGpuAssignment[gid] = devices.map(function(d) { return d.index; });
      } else {
        gladiatorGpuAssignment[gid] = [parseInt(val, 10)];
      }
      renderCardGpuSelector(gid, cardEl, fitResult);
      validateAllGpuAssignments();
    });
  });
}

// Check if assigned GPUs have enough VRAM for this model,
// accounting for other models already assigned to the same GPUs.
function checkGpuVramFeasibility(targetGid, assignedIndices, memNeededGb, devices) {
  if (!assignedIndices || !assignedIndices.length) return null;

  // Multi-GPU: total VRAM = sum across assigned devices
  var totalVramGb = assignedIndices.reduce(function(sum, idx) {
    var dev = devices.find(function(d) { return d.index === idx; });
    return sum + (dev && dev.memory_total_mb ? dev.memory_total_mb / 1024 : 0);
  }, 0);

  // Compute already-committed VRAM on these GPUs from other gladiators
  var committed = 0;
  Object.keys(gladiatorGpuAssignment).forEach(function(otherGid) {
    if (otherGid === targetGid) return;
    var otherAssigned = gladiatorGpuAssignment[otherGid];
    if (!otherAssigned || !otherAssigned.length) return;
    var overlaps = otherAssigned.some(function(i) { return assignedIndices.indexOf(i) !== -1; });
    if (!overlaps) return;
    var otherVariant = (function() {
      var glad = GLADIATORS.find(function(g) { return g.id === otherGid; });
      if (!glad) return null;
      var idx = gladiatorVariants[otherGid] || 0;
      return glad.variants[idx];
    })();
    if (!otherVariant) return;
    var otherNorm = normalizeLocalModelId(otherVariant.model);
    var otherFit = fitResultCache[otherNorm];
    if (otherFit && otherFit.memory_required_gb) committed += otherFit.memory_required_gb;
  });

  var remaining = totalVramGb - committed;
  if (memNeededGb > remaining) {
    return "Insufficient VRAM: need " + memNeededGb.toFixed(1) + " GB, " + remaining.toFixed(1) + " GB free (" + committed.toFixed(1) + "/" + totalVramGb.toFixed(0) + " GB used)";
  }
  if (assignedIndices.length > 1) {
    return "Multi-GPU ×" + assignedIndices.length + " · total VRAM " + totalVramGb.toFixed(0) + " GB";
  }
  return null;
}

// Re-validate all cards after assignment change
function validateAllGpuAssignments() {
  document.querySelectorAll('.gladiator-card[data-gid]').forEach(function(card) {
    var gid = card.dataset.gid;
    var glad = GLADIATORS.find(function(g) { return g.id === gid && g.tier === "free"; });
    if (!glad) return;
    var idx = gladiatorVariants[gid] || 0;
    var variant = glad.variants[idx];
    if (!variant) return;
    var norm = normalizeLocalModelId(variant.model);
    var fit = fitResultCache[norm];
    if (fit) renderCardGpuSelector(gid, card, fit);
  });
}

// Fetch fit for a gladiator card's inline badge (with cache)
function loadCardFitBadge(gid, modelId, cardEl) {
  if (!modelId) return;
  // Skip entirely if llmfit is not installed
  if (!localRuntimeState || !localRuntimeState.llmfit_installed) return;
  var normalized = normalizeLocalModelId(modelId);
  if (!normalized) return;
  var badgeEl = cardEl ? cardEl.querySelector(".card-fit-badge") : null;
  if (!badgeEl) return;

  var applyToCard = function(result) {
    applyFitResultToBadge(badgeEl, result);
    // Show/hide GPU selector based on whether model can potentially run
    var selectorEl = cardEl.querySelector(".card-gpu-selector");
    if (selectorEl) {
      if (result.fit_level !== "too_tight") {
        selectorEl.classList.remove("hidden");
        renderCardGpuSelector(gid, cardEl, result);
      } else {
        selectorEl.classList.add("hidden");
      }
    }
  };

  if (fitResultCache[normalized]) {
    applyToCard(fitResultCache[normalized]);
    return;
  }
  if (fitResultPending[normalized]) {
    badgeEl.textContent = "…";
    return;
  }
  fitResultPending[normalized] = true;
  badgeEl.textContent = "…";
  api("/local-models/fit-check?model=" + encodeURIComponent(normalized))
    .then(function(result) {
      fitResultCache[normalized] = result;
      delete fitResultPending[normalized];
      // Update ALL cards showing this model
      document.querySelectorAll('.card-fit-badge').forEach(function(el) {
        var parentCard = el.closest('[data-gid]');
        if (!parentCard) return;
        var gId = parentCard.dataset.gid;
        var glad = GLADIATORS.find(function(g) { return g.id === gId; });
        if (!glad) return;
        var vIdx = gladiatorVariants[gId] || 0;
        var v = glad.variants[vIdx];
        if (v && normalizeLocalModelId(v.model) === normalized) {
          applyFitResultToBadge(el, result);
          var sel = parentCard.querySelector(".card-gpu-selector");
          if (sel) {
            if (result.fit_level !== "too_tight") {
              sel.classList.remove("hidden");
              renderCardGpuSelector(gId, parentCard, result);
            } else {
              sel.classList.add("hidden");
            }
          }
        }
      });
    })
    .catch(function() { delete fitResultPending[normalized]; });
}


function fetchSetupStatus() {
  return api("/setup/status").then(function(statuses) {
    var states = {};
    statuses.forEach(function(s) {
      var groupId = s.tool === "codex" ? "openai" : s.tool;
      states[groupId] = s;
    });
    cliAuthStates = states;
    renderGladiatorGrid();
  }).catch(function() {});
}

function fetchLocalRuntimeStatus(ensureReady) {
  var suffix = ensureReady ? "?ensure_ready=true" : "";
  localRuntimeLoading = true;
  return api("/local-runtime/status" + suffix).then(function(status) {
    localRuntimeState = status;
    localRuntimeLoading = false;
    renderRegisteredList();
    // Now that we know llmfit status, reload fit badges on all free gladiator cards
    if (status.llmfit_installed) {
      document.querySelectorAll('.gladiator-card[data-gid]').forEach(function(card) {
        var gid = card.dataset.gid;
        var glad = GLADIATORS.find(function(g) { return g.id === gid && g.tier === "free"; });
        if (!glad) return;
        var idx = gladiatorVariants[gid] || 0;
        var variant = glad.variants[idx];
        if (variant) loadCardFitBadge(gid, variant.model, card);
      });
    }
    return status;
  }).catch(function(err) {
    localRuntimeLoading = false;
    throw err;
  });
}

function isGladiatorAuthBlocked(g) {
  var state = cliAuthStates[g.id];
  if (!state) return false;
  return state.installed && !state.auth_ok;
}

function triggerCLILogin(toolName, btn) {
  btn.disabled = true;
  btn.textContent = "Opening...";
  api("/setup/auth/" + toolName, { method: "POST" })
    .then(function(res) {
      if (res.status === "no_login_required") {
        toast("No login required for " + toolName + ".");
        fetchSetupStatus();
      } else {
        toast("Browser login opened. Complete login, then click Refresh.");
        btn.textContent = "Refresh";
        btn.disabled = false;
        btn.onclick = function(e) {
          e.stopPropagation();
          btn.textContent = "Checking...";
          btn.disabled = true;
          fetchSetupStatus().then(function() {
            btn.disabled = false;
            btn.textContent = "Refresh";
          });
        };
      }
    })
    .catch(function() {
      var state = cliAuthStates[toolName === "codex" ? "openai" : toolName];
      var loginCmd = state && state.login_cmd ? state.login_cmd : toolName + " login";
      toast("Could not launch login. Run manually: " + loginCmd);
      btn.textContent = "Login";
      btn.disabled = false;
    });
}

function fetchModels() {
  return api("/models").then(function(apiModels) {
    if (!apiModels || !apiModels.length) return;

    // Group API models by provider type
    var groups = {};
    apiModels.forEach(function(m) {
      var gInfo = PROVIDER_GROUP_MAP[m.type];
      if (!gInfo) return;
      var gid = gInfo.group;
      if (!groups[gid]) {
        groups[gid] = { id: gid, name: gInfo.name, icon: gInfo.icon, tier: gInfo.tier, desc: gInfo.desc, variants: [] };
      }
      var modelId = m.id.indexOf(":") !== -1 ? m.id.split(":").slice(1).join(":") : m.id;
      // For ollama, keep the "ollama:" prefix in model field
      var variantModel = m.type === "ollama" ? m.id : modelId;
      var variantType = m.type === "ollama" ? "huggingface_local" : m.type;
      // Avoid duplicate variants
      var exists = groups[gid].variants.some(function(v) { return v.model === variantModel; });
      if (!exists) {
        groups[gid].variants.push({ model: variantModel, label: m.name, type: variantType });
      }
    });

    // Merge into GLADIATORS: update existing entries, add new ones
    Object.keys(groups).forEach(function(gid) {
      var existing = null;
      var existingIdx = -1;
      GLADIATORS.forEach(function(g, i) {
        if (g.id === gid) { existing = g; existingIdx = i; }
      });

      if (existing) {
        // Merge variants: add new ones from API that aren't already present
        var apiGroup = groups[gid];
        apiGroup.variants.forEach(function(av) {
          var found = existing.variants.some(function(v) { return v.model === av.model; });
          if (!found) {
            existing.variants.push(av);
          }
        });
      } else {
        // Add new group (e.g. if ollama models are discovered but group didn't exist)
        GLADIATORS.push(groups[gid]);
      }
    });

    // Re-render if the gladiator grid is visible
    if (document.getElementById("gladiator-grid")) {
      renderGladiatorGrid();
    }
  }).catch(function(err) {
    // API not available — keep hardcoded GLADIATORS
  });
}

// Fetch live models on load
fetchModels();

// Fetch personas on load
function fetchPersonas() {
  return api("/personas").then(function(list) {
    availablePersonas = list || [];
    return availablePersonas;
  }).catch(function() {
    availablePersonas = [];
    return availablePersonas;
  });
}
fetchPersonas();

/* ── Helpers ── */
function esc(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function fmt(v) { return typeof v === "number" ? v.toFixed(2) : "-"; }
function show(id) { var el = document.getElementById(id); if (!el) return; el.classList.remove("hidden"); }
function hide(id) { var el = document.getElementById(id); if (!el) return; el.classList.add("hidden"); }
function reportUrl(runId) { return "/reports/" + encodeURIComponent(runId); }
function openReport(runId) {
  if (!runId) return;
  window.location.href = reportUrl(runId);
}

function toast(msg) {
  var el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(function() { el.classList.add("hidden"); }, 3500);
}

function resetPersonaSelectValue(gid) {
  if (!gid) return;
  var sel = document.querySelector('.persona-select[data-gid="' + gid + '"]');
  if (!sel) return;
  var persona = gladiatorPersonas[gid];
  if (persona && persona.persona_id && persona.persona_id !== "__custom__") sel.value = persona.persona_id;
  else sel.value = "";
}

function personaMetaById(personaId) {
  return (availablePersonas || []).find(function(p) { return p.persona_id === personaId; }) || null;
}

function humanizePersonaId(personaId) {
  var cleaned = String(personaId || "").replace(/^_+|_+$/g, "").replace(/[_-]+/g, " ").trim();
  if (!cleaned) return "";
  return cleaned.replace(/\b[a-z]/g, function(ch) { return ch.toUpperCase(); });
}

function extractPersonaNameFromContent(content) {
  var match = String(content || "").match(/^\s*#\s+(.+?)\s*$/m);
  if (match && match[1]) return match[1].trim();
  return "";
}

function col(title, items) {
  if (!items || !items.length) return "";
  return '<div class="round-col"><h4>' + esc(title) + '</h4>' + ul(items) + '</div>';
}

function ul(items) {
  if (!items || !items.length) return "";
  return '<ul>' + items.map(function(i) { return '<li>' + esc(i) + '</li>'; }).join("") + '</ul>';
}

function api(path, opts) {
  opts = opts || {};
  return fetch(path, {
    headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
    method: opts.method || "GET",
    body: opts.body || undefined
  }).then(function(r) {
    if (!r.ok) {
      return r.json().catch(function() { return {}; }).then(function(b) {
        throw new Error(b.detail || "Request failed: " + r.status);
      });
    }
    return r.json();
  });
}

function timeStr() {
  var d = new Date();
  var h = d.getHours();
  var m = d.getMinutes();
  var s = d.getSeconds();
  return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
}

function setBattleNote(message, busy) {
  var note = document.getElementById("battle-note");
  if (!note) return;
  note.textContent = message;
  if (busy) note.classList.add("busy");
  else note.classList.remove("busy");
}

function isImageUpload(file) {
  var type = (file && file.type) || "";
  var name = (file && file.name) || "";
  return /^image\//.test(type) || /\.(png|jpe?g|gif|webp|bmp|svg)$/i.test(name);
}

function guessImageMediaType(name) {
  var lower = String(name || "").toLowerCase();
  if (/\.png$/.test(lower)) return "image/png";
  if (/\.(jpg|jpeg)$/.test(lower)) return "image/jpeg";
  if (/\.gif$/.test(lower)) return "image/gif";
  if (/\.webp$/.test(lower)) return "image/webp";
  if (/\.bmp$/.test(lower)) return "image/bmp";
  if (/\.svg$/.test(lower)) return "image/svg+xml";
  return "image/png";
}

/* ── Render gladiator grid ── */
function renderGladiatorGrid() {
  var grid = document.getElementById("gladiator-grid");
  grid.innerHTML = "";

  var paidGladiators = GLADIATORS.filter(function(g) { return g.tier === "paid"; });
  var freeGladiators = GLADIATORS.filter(function(g) { return g.tier === "free"; });
  var paidCustomModels = customModels.filter(function(m) { return m.tier === "paid"; });
  var freeCustomModels = customModels.filter(function(m) { return m.tier !== "paid"; });

  // Paid section
  var paidHeader = document.createElement("div");
  paidHeader.className = "tier-header tier-paid";
  paidHeader.innerHTML = '<span class="tier-icon">\uD83D\uDC51</span> Premium Gladiators <span class="tier-badge paid">API</span>';
  grid.appendChild(paidHeader);

  var paidGrid = document.createElement("div");
  paidGrid.className = "tier-grid";
  paidGladiators.forEach(function(g) {
    paidGrid.appendChild(createGladiatorCard(g));
  });
  paidCustomModels.forEach(function(m) {
    paidGrid.appendChild(createCustomCard(m));
  });
  grid.appendChild(paidGrid);

  // Free section
  var freeHeader = document.createElement("div");
  freeHeader.className = "tier-header tier-free";
  freeHeader.innerHTML = '<span class="tier-icon">\uD83C\uDFDB\uFE0F</span> Open-Source Models <span class="tier-badge free">LOCAL</span>';
  grid.appendChild(freeHeader);

  var freeGrid = document.createElement("div");
  freeGrid.className = "tier-grid";
  freeGladiators.forEach(function(g) {
    var card = createGladiatorCard(g);
    freeGrid.appendChild(card);
    // Pre-load fit badge for default variant
    var idx = gladiatorVariants[g.id] || 0;
    var variant = g.variants[idx];
    if (variant) loadCardFitBadge(g.id, variant.model, card);
  });
  // Custom CLI models
  freeCustomModels.forEach(function(m) {
    freeGrid.appendChild(createCustomCard(m));
  });
  grid.appendChild(freeGrid);
  renderJudgeModelOptions();
}

function createGladiatorCard(g) {
  var authBlocked = isGladiatorAuthBlocked(g);
  var isDisabled = authBlocked;
  if (isDisabled && selectedGladiators[g.id]) delete selectedGladiators[g.id];
  var card = document.createElement("div");
  card.className = "gladiator-card" + (selectedGladiators[g.id] ? " selected" : "") + (isDisabled ? " disabled-card" : "") + (authBlocked ? " auth-blocked" : "");
  card.dataset.gid = g.id;

  var html = '<div class="gladiator-icon">' + g.icon + '</div>';
  html += '<div class="gladiator-name">' + esc(g.name) + '</div>';
  if (g.desc) {
    html += '<div class="gladiator-desc">' + esc(g.desc) + '</div>';
  }
  if (authBlocked) {
    html += '<div class="auth-chip">Not authenticated</div>';
  }

  // Variant select
  html += '<select class="gladiator-select" data-gid="' + esc(g.id) + '"' + (isDisabled ? ' disabled' : '') + '>';
  var currentIdx = gladiatorVariants[g.id] || 0;
  g.variants.forEach(function(v, i) {
    html += '<option value="' + i + '"' + (i === currentIdx ? ' selected' : '') + '>' + esc(v.label) + '</option>';
  });
  html += '</select>';

  // Fit badge + GPU selector (free/local models only)
  if (g.tier === "free") {
    html += '<div class="card-fit-badge" data-gid="' + esc(g.id) + '"></div>';
    html += '<div class="card-gpu-selector hidden" data-gid="' + esc(g.id) + '"></div>';
  }

  // Persona select
  html += '<select class="persona-select" data-gid="' + esc(g.id) + '" title="Assign a debating persona"' + (isDisabled ? ' disabled' : '') + '>';
  html += '<option value="">-- Persona --</option>';
  var hasBuiltin = false;
  var hasCustom = false;
  availablePersonas.forEach(function(p) {
    if (p.source === "custom" && !hasCustom) {
      hasCustom = true;
      if (hasBuiltin) html += '<option disabled>───────</option>';
      html += '<option disabled>Custom Personas</option>';
    } else if (p.source !== "custom" && !hasBuiltin) {
      hasBuiltin = true;
    }
    var selAttr = (gladiatorPersonas[g.id] && gladiatorPersonas[g.id].persona_id === p.persona_id) ? ' selected' : '';
    var label = p.name;
    if (p.description) label += ' - ' + p.description.slice(0, 40);
    html += '<option value="' + esc(p.persona_id) + '"' + selAttr + ' title="' + esc(p.description || '') + '">' + esc(label) + '</option>';
  });
  html += '<option disabled>───────</option>';
  html += '<option value="__generate__">+ Build From Profile...</option>';
  html += '<option value="__custom__">+ Write Custom...</option>';
  html += '</select>';

  if (authBlocked) {
    var toolName = CLI_GROUP_TOOL_MAP[g.id];
    if (toolName) {
      html += '<button class="btn-cli-login" data-tool="' + esc(toolName) + '">Login</button>';
    }
  }

  card.innerHTML = html;

  if (authBlocked) {
    var loginBtn = card.querySelector(".btn-cli-login");
    if (loginBtn) {
      loginBtn.addEventListener("click", function(e) {
        e.stopPropagation();
        triggerCLILogin(loginBtn.dataset.tool, loginBtn);
      });
    }
  }

  // Click card to toggle selection (not when clicking select)
  card.addEventListener("click", function(e) {
    if (e.target.tagName === "SELECT" || e.target.tagName === "OPTION") return;
    if (e.target.tagName === "BUTTON") return;
    if (authBlocked) {
      toast(g.name + " is not authenticated. Click Login to sign in.");
      return;
    }
    if (selectedGladiators[g.id]) {
      delete selectedGladiators[g.id];
    } else {
      selectedGladiators[g.id] = true;
      if (g.tier === "free") {
        var selIdx = gladiatorVariants[g.id] || 0;
        var variant = g.variants[selIdx];
        if (variant) loadCardFitBadge(g.id, variant.model, card);
      }
    }
    card.classList.toggle("selected", !!selectedGladiators[g.id]);
  });

  // Variant change
  var varSel = card.querySelector(".gladiator-select");
  varSel.addEventListener("change", function() {
    gladiatorVariants[g.id] = parseInt(varSel.value);
    // Refresh fit badge and GPU selector on variant change for free models
    if (g.tier === "free") {
      var newVariant = g.variants[gladiatorVariants[g.id]];
      if (newVariant) {
        gladiatorGpuAssignment[g.id] = null; // reset GPU choice when variant changes
        loadCardFitBadge(g.id, newVariant.model, card);
      }
    }
  });

  // Persona change
  var perSel = card.querySelector(".persona-select");
  perSel.addEventListener("change", function() {
    var val = perSel.value;
    if (val === "__generate__") {
      openPersonaBuilderModal(g.id);
    } else if (val === "__custom__") {
      openPersonaModal(g.id);
    } else if (val) {
      // Fetch persona content
      api("/personas/" + val).then(function(data) {
        var meta = personaMetaById(val);
        gladiatorPersonas[g.id] = {
          persona_id: val,
          persona_name: meta ? meta.name : humanizePersonaId(val),
          persona_content: data.content
        };
      }).catch(function() {
        toast("Failed to load persona.");
        perSel.value = "";
        delete gladiatorPersonas[g.id];
      });
    } else {
      delete gladiatorPersonas[g.id];
    }
  });

  return card;
}

function createCustomCard(m) {
  var card = document.createElement("div");
  card.className = "gladiator-card" + (selectedGladiators[m.id] ? " selected" : "");
  card.dataset.gid = m.id;

  var html = '<div class="gladiator-icon">\u2699\uFE0F</div>';
  html += '<div class="gladiator-name">' + esc(m.name) + '</div>';
  html += '<div style="font-size:0.72rem;color:var(--sand-muted)">' + esc(m.desc) + '</div>';
  html += '<select class="persona-select" data-gid="' + esc(m.id) + '">';
  html += '<option value="">-- Persona --</option>';
  availablePersonas.forEach(function(p) {
    var selAttr = (gladiatorPersonas[m.id] && gladiatorPersonas[m.id].persona_id === p.persona_id) ? ' selected' : '';
    html += '<option value="' + esc(p.persona_id) + '"' + selAttr + '>' + esc(p.name) + '</option>';
  });
  html += '<option disabled>───────</option>';
  html += '<option value="__generate__">+ Build From Profile...</option>';
  html += '<option value="__custom__">+ Write Custom...</option>';
  html += '</select>';

  card.innerHTML = html;
  card.addEventListener("click", function(e) {
    if (e.target.tagName === "SELECT" || e.target.tagName === "OPTION") return;
    if (selectedGladiators[m.id]) {
      delete selectedGladiators[m.id];
    } else {
      selectedGladiators[m.id] = true;
    }
    card.classList.toggle("selected", !!selectedGladiators[m.id]);
  });

  var perSel = card.querySelector(".persona-select");
  perSel.addEventListener("change", function() {
    var val = perSel.value;
    if (val === "__generate__") {
      openPersonaBuilderModal(m.id);
    } else if (val === "__custom__") {
      openPersonaModal(m.id);
    } else if (val) {
      api("/personas/" + val).then(function(data) {
        var meta = personaMetaById(val);
        gladiatorPersonas[m.id] = {
          persona_id: val,
          persona_name: meta ? meta.name : humanizePersonaId(val),
          persona_content: data.content
        };
      }).catch(function() {
        toast("Failed to load persona.");
        perSel.value = "";
        delete gladiatorPersonas[m.id];
      });
    } else {
      delete gladiatorPersonas[m.id];
    }
  });

  return card;
}

// ── Dynamic model discovery from /models API ──
var _modelPollTimer = null;

function refreshGladiatorsFromAPI() {
  api("/models").then(function(models) {
    if (!models || !models.length) return;

    // Group by provider
    var byProvider = {};
    models.forEach(function(m) {
      var provider = m.provider || m.id.split(":")[0];
      if (!byProvider[provider]) byProvider[provider] = [];
      byProvider[provider].push(m);
    });

    // Rebuild paid gladiators from API response
    var providerMeta = {
      claude:  { name: "Claude",   icon: "\u2694\uFE0F",          desc: "claude -p --model <model>", tier: "paid" },
      codex:   { name: "OpenAI",   icon: "\uD83D\uDEE1\uFE0F",   desc: "codex --model <model> -p",  tier: "paid" },
      gemini:  { name: "Gemini",   icon: "\uD83D\uDD31",          desc: "gemini --model <model> -p", tier: "paid" },
      ollama:  { name: "Ollama",   icon: "\uD83E\uDD99",          desc: "ollama run <model>",        tier: "free" }
    };

    var newGladiators = [];
    var paidProviders = ["claude", "codex", "gemini"];

    paidProviders.forEach(function(provider) {
      var pModels = byProvider[provider];
      if (!pModels || !pModels.length) return;
      var meta = providerMeta[provider] || { name: provider, icon: "", desc: "", tier: "paid" };
      // Map provider id to gladiator id (codex -> openai for display)
      var gid = provider === "codex" ? "openai" : provider;
      newGladiators.push({
        id: gid,
        name: meta.name,
        icon: meta.icon || (pModels[0].icon || ""),
        tier: meta.tier,
        desc: meta.desc,
        variants: pModels.map(function(m) {
          return {
            model: m.model || m.id.split(":")[1] || m.id,
            label: m.label || m.name,
            type: m.type || "command"
          };
        })
      });
    });

    // Rebuild free gladiators: group ollama models by family
    var ollamaModels = byProvider["ollama"] || [];
    if (ollamaModels.length > 0) {
      var ollamaFamilies = {};
      var familyIcons = {
        llama: "\uD83E\uDD99", mistral: "\uD83C\uDF2A\uFE0F", qwen: "\uD83C\uDFEF",
        gemma: "\uD83D\uDC8E", phi: "\uD83E\uDDE0", deepseek: "\uD83D\uDD2D"
      };
      ollamaModels.forEach(function(m) {
        var modelName = m.model || m.id.split(":")[1] || m.id;
        var family = modelName.replace(/[0-9.:_-].*/g, "").toLowerCase();
        if (!family) family = "other";
        if (!ollamaFamilies[family]) ollamaFamilies[family] = [];
        ollamaFamilies[family].push({
          model: "ollama:" + modelName,
          label: m.label || m.name,
          type: "huggingface_local"
        });
      });
      Object.keys(ollamaFamilies).forEach(function(family) {
        var displayName = family.charAt(0).toUpperCase() + family.slice(1);
        var familyVariants = ollamaFamilies[family];
        // Prepend "Auto" variant — resolves to the first installed model in this family
        var autoVariant = { model: familyVariants[0].model, label: "Auto", type: "huggingface_local" };
        var variants = familyVariants.length > 1
          ? [autoVariant].concat(familyVariants)
          : familyVariants;
        newGladiators.push({
          id: family,
          name: displayName,
          icon: familyIcons[family] || "\uD83E\uDD16",
          tier: "free",
          desc: "ollama run <model>",
          variants: variants
        });
      });
    } else {
      // Keep existing free gladiators from hardcoded list as fallback
      GLADIATORS.forEach(function(g) {
        if (g.tier === "free") newGladiators.push(g);
      });
    }

    // Only update if we actually got paid models
    if (newGladiators.some(function(g) { return g.tier === "paid"; })) {
      GLADIATORS = newGladiators;
      // Reset variant indices for gladiators whose variant count changed
      GLADIATORS.forEach(function(g) {
        var idx = gladiatorVariants[g.id] || 0;
        if (idx >= g.variants.length) gladiatorVariants[g.id] = 0;
      });
      renderGladiatorGrid();
      console.log("[Colosseum] Models refreshed from server:", models.length, "models across", Object.keys(byProvider).length, "providers");
    }

    // Stop polling once probed models arrive (they have 'provider' field)
    if (models.some(function(m) { return m.provider; }) && _modelPollTimer) {
      clearInterval(_modelPollTimer);
      _modelPollTimer = null;
    }
  }).catch(function() {
    // Silently use hardcoded fallback
  });
}

// Default selection
selectedGladiators["claude"] = true;
selectedGladiators["gemini"] = true;
renderGladiatorGrid();
fetchSetupStatus();
fetchLocalRuntimeStatus(false);  // populate GPU panel and fit badges on load

// Fetch dynamic models — poll every 5s until probed results arrive
refreshGladiatorsFromAPI();
_modelPollTimer = setInterval(refreshGladiatorsFromAPI, 5000);
syncCustomModelForm();

document.getElementById("build-persona-btn").addEventListener("click", function() {
  openPersonaBuilderModal(null);
});

document.getElementById("back-to-setup").addEventListener("click", function() {
  show("setup");
});

/* ── Skip round ── */
var skipRoundBtn = document.getElementById("skip-round-btn");
skipRoundBtn.addEventListener("click", function() {
  if (!currentRunId) return;
  skipRoundBtn.disabled = true;
  skipRoundBtn.textContent = "Skipping...";
  fetch("/runs/" + encodeURIComponent(currentRunId) + "/skip-round", { method: "POST" })
    .then(function(res) { return res.json(); })
    .catch(function(err) {
      console.error("Skip round failed:", err);
      toast("Skip round failed.");
    })
    .finally(function() {
      skipRoundBtn.disabled = false;
      skipRoundBtn.textContent = "Skip Round";
    });
});

/* ── Cancel debate ── */
var cancelDebateBtn = document.getElementById("cancel-debate-btn");
cancelDebateBtn.addEventListener("click", function() {
  if (!currentRunId) return;
  if (!confirm("Cancel the entire debate? This will stop all rounds immediately.")) return;
  cancelDebateBtn.disabled = true;
  cancelDebateBtn.textContent = "Cancelling...";
  fetch("/runs/" + encodeURIComponent(currentRunId) + "/cancel", { method: "POST" })
    .then(function(res) { return res.json(); })
    .catch(function(err) {
      console.error("Cancel debate failed:", err);
      toast("Cancel debate failed.");
    })
    .finally(function() {
      cancelDebateBtn.disabled = false;
      cancelDebateBtn.textContent = "Cancel Debate";
    });
});

/* ── Depth slider ── */
var depthSlider = document.getElementById("depth");
var depthVal = document.getElementById("depth-val");
var DEPTH_LABELS = {
  1: "Quick",
  2: "Brief",
  3: "Standard",
  4: "Thorough",
  5: "Deep Dive"
};
var DEPTH_PROFILES = {
  1: { min_novelty: 0.05, convergence: 0.40, confidence: 0.55, min_rounds: 1 },
  2: { min_novelty: 0.10, convergence: 0.55, confidence: 0.65, min_rounds: 1 },
  3: { min_novelty: 0.18, convergence: 0.75, confidence: 0.78, min_rounds: 1 },
  4: { min_novelty: 0.25, convergence: 0.85, confidence: 0.85, min_rounds: 2 },
  5: { min_novelty: 0.30, convergence: 0.92, confidence: 0.92, min_rounds: 2 }
};
var timeoutInput = document.getElementById("timeout-input");
var timeoutNolimit = document.getElementById("timeout-nolimit");

timeoutNolimit.addEventListener("change", function() {
  timeoutInput.disabled = timeoutNolimit.checked;
});

depthSlider.addEventListener("input", function() {
  var v = parseInt(depthSlider.value);
  depthVal.textContent = v + (v === 1 ? " round" : " rounds") + " — " + (DEPTH_LABELS[v] || "");
});

/* ── Mode toggle ── */
var modeLive = document.getElementById("mode-live");
var modeResult = document.getElementById("mode-result");

modeLive.addEventListener("click", function() {
  currentMode = "live";
  modeLive.classList.add("active");
  modeResult.classList.remove("active");
});

modeResult.addEventListener("click", function() {
  currentMode = "result";
  modeResult.classList.add("active");
  modeLive.classList.remove("active");
});

/* ── Judge toggle ── */
var judgeAuto = document.getElementById("judge-auto");
var judgeAi = document.getElementById("judge-ai");
var judgeHuman = document.getElementById("judge-human");
var judgeModelWrap = document.getElementById("judge-model-wrap");
var judgeModelSelect = document.getElementById("judge-model");
var judgeNote = document.getElementById("judge-note");
var evidenceJudgingToggle = document.getElementById("evidence-judging-toggle");
var evidenceJudgingNote = document.getElementById("evidence-judging-note");
var searchToggle = document.getElementById("encourage-search-toggle");
var searchNote = document.getElementById("search-note");

var JUDGE_NOTES = {
  automated: "Colosseum's built-in judge balances evidence quality, disagreement, and budget pressure.",
  ai: "Choose a model to act as the judge for each round and the final verdict.",
  human: "You will review each round and decide the outcome yourself."
};

function updateJudgeControls() {
  if (judgeAuto) {
    if (currentJudgeMode === "automated") judgeAuto.classList.add("active");
    else judgeAuto.classList.remove("active");
  }
  if (judgeAi) {
    if (currentJudgeMode === "ai") judgeAi.classList.add("active");
    else judgeAi.classList.remove("active");
  }
  if (judgeHuman) {
    if (currentJudgeMode === "human") judgeHuman.classList.add("active");
    else judgeHuman.classList.remove("active");
  }
  if (judgeModelWrap) {
    if (currentJudgeMode === "ai") judgeModelWrap.classList.remove("hidden");
    else judgeModelWrap.classList.add("hidden");
  }
  if (!judgeNote) return;
  if (currentJudgeMode !== "ai") {
    judgeNote.textContent = JUDGE_NOTES[currentJudgeMode] || JUDGE_NOTES.automated;
    return;
  }
  var option = getSelectedJudgeModelOption();
  if (!option) {
    judgeNote.textContent = "Pick a judge model before starting the run.";
    return;
  }
  judgeNote.textContent = option.label + " will review each round, set the next agenda, and deliver the final verdict.";
}

function updateEvidenceJudgingUI() {
  if (evidenceJudgingToggle) evidenceJudgingToggle.checked = !!useEvidenceBasedJudging;
  if (!evidenceJudgingNote) return;
  if (useEvidenceBasedJudging) {
    evidenceJudgingNote.textContent = "When enabled, thin evidence can force another round and evidence grounding weighs more heavily in scoring and finalization.";
    return;
  }
  evidenceJudgingNote.textContent = "When disabled, evidence is still shown to the judge, but it no longer acts as a hard gate for continuing or finalizing the debate.";
}

judgeAuto.addEventListener("click", function() {
  currentJudgeMode = "automated";
  updateJudgeControls();
});

judgeAi.addEventListener("click", function() {
  currentJudgeMode = "ai";
  updateJudgeControls();
});

judgeHuman.addEventListener("click", function() {
  currentJudgeMode = "human";
  updateJudgeControls();
});

if (judgeModelSelect) {
  judgeModelSelect.addEventListener("change", updateJudgeControls);
}

renderJudgeModelOptions();
updateJudgeControls();
updateEvidenceJudgingUI();
updateSearchPreferenceUI();

if (evidenceJudgingToggle) {
  evidenceJudgingToggle.addEventListener("change", function() {
    useEvidenceBasedJudging = !!evidenceJudgingToggle.checked;
    saveBooleanSetting("colosseum:evidence_judging", useEvidenceBasedJudging);
    updateEvidenceJudgingUI();
  });
}

function updateSearchPreferenceUI() {
  if (searchToggle) searchToggle.checked = !!encourageInternetSearch;
  if (!searchNote) return;
  if (encourageInternetSearch) {
    searchNote.textContent = "When enabled, agents are encouraged to check authoritative web sources if their provider supports browsing. If not, they must say so instead of guessing.";
  } else {
    searchNote.textContent = "When disabled, agents are pushed to stay inside the frozen bundle, avoid memory-based fill-ins, and mark uncertainty explicitly.";
  }
}

if (searchToggle) {
  searchToggle.addEventListener("change", function() {
    encourageInternetSearch = !!searchToggle.checked;
    saveBooleanSetting("colosseum:encourage_search", encourageInternetSearch);
    updateSearchPreferenceUI();
  });
}


/* ── File attachments ── */
var fileDrop = document.getElementById("file-drop");
var fileInput = document.getElementById("file-input");

fileDrop.addEventListener("click", function() { fileInput.click(); });
fileDrop.addEventListener("dragover", function(e) { e.preventDefault(); fileDrop.classList.add("dragover"); });
fileDrop.addEventListener("dragleave", function() { fileDrop.classList.remove("dragover"); });
fileDrop.addEventListener("drop", function(e) {
  e.preventDefault();
  fileDrop.classList.remove("dragover");
  handleFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", function() { handleFiles(fileInput.files); fileInput.value = ""; });

function handleFiles(fileList) {
  Array.from(fileList).forEach(function(file) {
    var isImage = isImageUpload(file);
    var maxBytes = isImage ? MAX_IMAGE_FILE_BYTES : MAX_TEXT_FILE_BYTES;
    if (file.size > maxBytes) {
      toast(file.name + " is too large (max " + (isImage ? "4 MB for images" : "100 KB for text") + ").");
      return;
    }
    var reader = new FileReader();
    reader.onload = function() {
      attachedFiles.push({
        name: file.name,
        content: reader.result,
        size: file.size,
        kind: isImage ? "inline_image" : "inline_text",
        mediaType: isImage ? (file.type || guessImageMediaType(file.name)) : "text/plain"
      });
      renderFileList();
    };
    if (isImage) reader.readAsDataURL(file);
    else reader.readAsText(file);
  });
}

function renderFileList() {
  var list = document.getElementById("file-list");
  if (!attachedFiles.length) { list.innerHTML = ""; return; }
  list.innerHTML = attachedFiles.map(function(f, i) {
    var sizeStr = f.size < 1024 ? f.size + " B" : (f.size / 1024).toFixed(1) + " KB";
    var kindLabel = f.kind === "inline_image" ? "Image" : "Text";
    var mediaLabel = f.kind === "inline_image" ? (f.mediaType || "image") : "plain text";
    var thumb = f.kind === "inline_image"
      ? '<img class="file-thumb" src="' + esc(f.content) + '" alt="' + esc(f.name) + '"/>'
      : '<div class="file-thumb file-thumb-text">TXT</div>';
    return '<div class="file-item">' +
      '<div class="file-item-main">' +
      thumb +
      '<div class="file-item-copy">' +
      '<span class="file-item-name">' + esc(f.name) + '</span>' +
      '<span class="file-item-meta"><span class="file-badge file-badge-' + esc(f.kind || "inline_text") + '">' + esc(kindLabel) + '</span>' +
      '<span class="file-item-size">' + esc(mediaLabel) + ' · ' + sizeStr + '</span></span>' +
      '</div></div>' +
      '<span>' +
      '<button class="remove-btn" data-fi="' + i + '">Remove</button></span>' +
      '</div>';
  }).join("");
  list.querySelectorAll(".remove-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      attachedFiles.splice(parseInt(btn.dataset.fi), 1);
      renderFileList();
    });
  });
}

/* ── CLI Registration ── */
document.getElementById("add-cli-btn").addEventListener("click", function() {
  var form = document.getElementById("cli-form");
  form.classList.toggle("hidden");
  syncCustomModelForm();
});


function syncCustomModelForm() {
  var type = document.getElementById("cli-type").value;
  var cmd = document.getElementById("cli-cmd");
  var modelInput = document.getElementById("cli-model-id");
  if (type === "command") {
    cmd.disabled = false;
    cmd.placeholder = "CLI command (e.g. /opt/my_model_cli --json)";
    modelInput.placeholder = "Model id (optional)";
  } else if (type === "ollama") {
    cmd.disabled = true;
    cmd.value = "";
    modelInput.placeholder = "Ollama model id (e.g. my-model:latest)";
  } else {
    cmd.disabled = true;
    cmd.value = "";
    modelInput.placeholder = "Local HF/Ollama model id (e.g. org/model or llama3.3)";
  }
  if (
    isLocalModelType(type) &&
    !localRuntimeLoading &&
    (!localRuntimeState || !localRuntimeState.installed_models_known)
  ) {
    fetchLocalRuntimeStatus(true).catch(function(err) {
      toast("Could not inspect local runtime: " + (err.message || ""));
    });
  }
}

document.getElementById("cli-type").addEventListener("change", syncCustomModelForm);

document.getElementById("cli-save").addEventListener("click", function() {
  var name = document.getElementById("cli-name").value.trim();
  var providerType = document.getElementById("cli-type").value;
  var cmd = document.getElementById("cli-cmd").value.trim();
  var modelId = document.getElementById("cli-model-id").value.trim();
  var desc = document.getElementById("cli-desc").value.trim();
  if (!name) return toast("Enter a name for the gladiator.");
  if (providerType === "command" && !cmd) return toast("Enter the CLI command.");
  if (providerType !== "command" && !modelId) return toast("Enter the model id.");

  var id = "custom-" + name.toLowerCase().replace(/[^a-z0-9]/g, "-");

  // Check duplicate
  var allIds = GLADIATORS.map(function(g) { return g.id; }).concat(customModels.map(function(m) { return m.id; }));
  if (allIds.indexOf(id) !== -1) {
    return toast("A gladiator with this name already exists.");
  }

  var newModel = normalizeCustomModel({
    id: id,
    name: name,
    desc: desc || (providerType === "command" ? cmd.split(" ")[0] : modelId),
    type: providerType,
    tier: "free",
    model: modelId || name,
    command: providerType === "command" ? cmd.split(" ").filter(Boolean) : []
  });

  customModels.push(newModel);
  saveCustomModels(customModels);
  renderGladiatorGrid();
  renderRegisteredList();

  document.getElementById("cli-name").value = "";
  document.getElementById("cli-model-id").value = "";
  document.getElementById("cli-cmd").value = "";
  document.getElementById("cli-desc").value = "";
  document.getElementById("cli-form").classList.add("hidden");
  syncCustomModelForm();

  toast("Forged: " + name);
});

/* ── HuggingFace Hub Browser ── */
var _hfInstalledModels = [];

var HF_POPULAR_MODELS = [
  { repo_id: "unsloth/Llama-3.2-1B-Instruct-GGUF", desc: "Llama 3.2 1B", size: "~1 GB", tag: "Small & fast" },
  { repo_id: "bartowski/Llama-3.2-3B-Instruct-GGUF", desc: "Llama 3.2 3B", size: "~2 GB", tag: "Balanced" },
  { repo_id: "bartowski/Llama-3.3-70B-Instruct-GGUF", desc: "Llama 3.3 70B", size: "~40 GB", tag: "Powerful" },
  { repo_id: "bartowski/Mistral-7B-Instruct-v0.3-GGUF", desc: "Mistral 7B v0.3", size: "~4 GB", tag: "Popular" },
  { repo_id: "bartowski/gemma-2-9b-it-GGUF", desc: "Gemma 2 9B", size: "~5 GB", tag: "Google" },
  { repo_id: "bartowski/Qwen2.5-7B-Instruct-GGUF", desc: "Qwen 2.5 7B", size: "~4 GB", tag: "Multilingual" },
  { repo_id: "bartowski/Phi-3.5-mini-instruct-GGUF", desc: "Phi 3.5 Mini", size: "~2 GB", tag: "Compact" },
  { repo_id: "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF", desc: "DeepSeek R1 7B", size: "~4 GB", tag: "Reasoning" },
];

function hfModelDisplayName(repoId) {
  var parts = repoId.split("/");
  var name = parts.length > 1 ? parts[1] : parts[0];
  return name.replace(/-GGUF$/i, "").replace(/-/g, " ");
}

function isHfModelInstalled(repoId) {
  return _hfInstalledModels.some(function(m) { return m.indexOf(repoId) !== -1; });
}

function refreshHfInstalledModels() {
  api("/hf/models").then(function(list) {
    _hfInstalledModels = list || [];
    var countEl = document.getElementById("hf-installed-count");
    if (countEl) {
      countEl.textContent = _hfInstalledModels.length
        ? _hfInstalledModels.length + " model" + (_hfInstalledModels.length > 1 ? "s" : "") + " installed"
        : "";
    }
    renderHfPopular();
  }).catch(function() {});
}

function renderHfPopular() {
  var container = document.getElementById("hf-popular");
  if (!container) return;
  var html = '<div class="hf-popular-label">Popular Models</div><div class="hf-card-grid">';
  HF_POPULAR_MODELS.forEach(function(m) {
    var installed = isHfModelInstalled(m.repo_id);
    html += '<div class="hf-card' + (installed ? ' hf-card-installed' : '') + '" data-repo="' + esc(m.repo_id) + '">';
    html += '<div class="hf-card-tag">' + esc(m.tag) + '</div>';
    html += '<div class="hf-card-name">' + esc(m.desc) + '</div>';
    html += '<div class="hf-card-meta">';
    html += '<span class="hf-card-size">' + esc(m.size) + '</span>';
    html += '<span class="hf-card-author">' + esc(m.repo_id.split("/")[0]) + '</span>';
    html += '</div>';
    if (installed) {
      html += '<div class="hf-card-status hf-card-ready">Ready</div>';
    } else {
      html += '<button class="hf-card-dl-btn" data-repo="' + esc(m.repo_id) + '">Download</button>';
    }
    html += '</div>';
  });
  html += '</div>';
  container.innerHTML = html;

  container.querySelectorAll(".hf-card-dl-btn").forEach(function(btn) {
    btn.addEventListener("click", function(e) {
      e.stopPropagation();
      pullHuggingFaceModel(btn.dataset.repo, btn);
    });
  });
}

document.getElementById("hf-search-btn").addEventListener("click", searchHuggingFace);
document.getElementById("hf-search-input").addEventListener("keydown", function(e) {
  if (e.key === "Enter") searchHuggingFace();
});

function searchHuggingFace() {
  var query = document.getElementById("hf-search-input").value.trim();
  if (!query) return;
  var resultsEl = document.getElementById("hf-search-results");
  var popularEl = document.getElementById("hf-popular");
  if (popularEl) popularEl.classList.add("hidden");
  resultsEl.innerHTML = '<div class="hf-loading">Searching HuggingFace Hub...</div>';

  api("/hf/search?q=" + encodeURIComponent(query) + "&limit=20")
    .then(function(data) {
      if (!data.results || !data.results.length) {
        resultsEl.innerHTML = '<div class="hf-empty">No GGUF models found for "' + esc(query) + '"</div>';
        return;
      }
      var html = '<div class="hf-results-header">' + data.results.length + ' results <button class="text-btn hf-clear-btn">Clear</button></div>';
      html += '<div class="hf-card-grid">';
      data.results.forEach(function(m) {
        var installed = isHfModelInstalled(m.repo_id);
        var dlCount = (m.downloads || 0) >= 1000 ? Math.round((m.downloads || 0) / 1000) + "K" : String(m.downloads || 0);
        html += '<div class="hf-card' + (installed ? ' hf-card-installed' : '') + '" data-repo="' + esc(m.repo_id) + '">';
        html += '<div class="hf-card-tag">' + dlCount + ' DL</div>';
        html += '<div class="hf-card-name">' + esc(hfModelDisplayName(m.repo_id)) + '</div>';
        html += '<div class="hf-card-meta">';
        html += '<span class="hf-card-author">' + esc(m.author || "") + '</span>';
        html += '</div>';
        if (installed) {
          html += '<div class="hf-card-status hf-card-ready">Ready</div>';
        } else {
          html += '<button class="hf-card-dl-btn" data-repo="' + esc(m.repo_id) + '">Download</button>';
        }
        html += '</div>';
      });
      html += '</div>';
      resultsEl.innerHTML = html;
      resultsEl.querySelectorAll(".hf-card-dl-btn").forEach(function(btn) {
        btn.addEventListener("click", function(e) {
          e.stopPropagation();
          pullHuggingFaceModel(btn.dataset.repo, btn);
        });
      });
      var clearBtn = resultsEl.querySelector(".hf-clear-btn");
      if (clearBtn) clearBtn.addEventListener("click", function() {
        resultsEl.innerHTML = "";
        if (popularEl) popularEl.classList.remove("hidden");
        document.getElementById("hf-search-input").value = "";
      });
    })
    .catch(function(e) {
      resultsEl.innerHTML = '<div class="hf-error">Search failed: ' + esc(e.message || "") + '</div>';
    });
}

function pullHuggingFaceModel(repoId, btnEl) {
  if (btnEl) {
    btnEl.disabled = true;
    btnEl.textContent = "Downloading...";
    btnEl.classList.add("hf-downloading");
  }
  fetch("/hf/pull", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_id: repoId })
  })
  .then(function(r) {
    if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || "Pull failed"); });
    return r.json();
  })
  .then(function() {
    if (btnEl) {
      btnEl.textContent = "Ready";
      btnEl.classList.remove("hf-downloading");
      btnEl.classList.add("hf-pull-done");
    }
    toast(hfModelDisplayName(repoId) + " is ready to use!");
    refreshGladiatorsFromAPI();
    refreshHfInstalledModels();
    fetchLocalRuntimeStatus(false);
  })
  .catch(function(e) {
    if (btnEl) {
      btnEl.textContent = "Retry";
      btnEl.disabled = false;
      btnEl.classList.remove("hf-downloading");
    }
    toast("Download failed: " + (e.message || ""));
  });
}

// Load HF state on startup
refreshHfInstalledModels();

function renderRegisteredList() {
  var list = document.getElementById("registered-list");
  if (!customModels.length) { list.innerHTML = ""; return; }
  list.innerHTML = customModels.map(function(m) {
    var runtimeState = "";
    if (isLocalModelType(m.type) && localRuntimeState && localRuntimeState.installed_models_known) {
      runtimeState = isLocalModelInstalled(m.model)
        ? ' <span class="runtime-badge ok">installed</span>'
        : ' <span class="runtime-badge warn">missing</span>';
    }
    return '<div class="registered-item">' +
      '<span>' + esc(m.name) + runtimeState + ' <small>(' + esc(m.type) + ' · ' + esc(m.tier) + ' · ' + esc(m.desc) + ')</small></span>' +
      '<button class="remove-btn" data-rid="' + esc(m.id) + '">Remove</button>' +
      '</div>';
  }).join("");

  list.querySelectorAll(".remove-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var rid = btn.dataset.rid;
      customModels = customModels.filter(function(m) { return m.id !== rid; });
      delete selectedGladiators[rid];
      saveCustomModels(customModels);
      renderGladiatorGrid();
      renderRegisteredList();
      toast("Removed.");
    });
  });
}
renderRegisteredList();

/* ── Persona modal ── */
var personaModalTarget = null;  // gladiator id being edited
var personaModalMode = "apply"; // "apply" or "preview"

function openPersonaModal(gid) {
  personaModalTarget = gid;
  personaModalMode = "apply";
  var nameField = document.getElementById("persona-name");
  var editor = document.getElementById("persona-editor");
  nameField.value = "";
  editor.value = (gladiatorPersonas[gid] && gladiatorPersonas[gid].persona_content) || "";
  document.getElementById("persona-modal-title").textContent = "Custom Persona";
  document.getElementById("persona-name-row").classList.remove("hidden");
  document.getElementById("persona-apply-btn").classList.remove("hidden");
  document.getElementById("persona-save-server-btn").classList.remove("hidden");
  editor.readOnly = false;
  show("persona-modal");
}

function openPersonaModalWithDraft(name, content, gid) {
  personaModalTarget = gid || null;
  personaModalMode = "apply";
  var nameField = document.getElementById("persona-name");
  var editor = document.getElementById("persona-editor");
  nameField.value = name || "";
  editor.value = content || "";
  document.getElementById("persona-modal-title").textContent = gid ? "Custom Persona" : "Generated Persona";
  document.getElementById("persona-name-row").classList.remove("hidden");
  if (gid) document.getElementById("persona-apply-btn").classList.remove("hidden");
  else document.getElementById("persona-apply-btn").classList.add("hidden");
  document.getElementById("persona-save-server-btn").classList.remove("hidden");
  editor.readOnly = false;
  show("persona-modal");
}

function openPersonaBuilderModal(gid) {
  personaBuilderTarget = gid || null;
  document.getElementById("builder-persona-name").value = "";
  document.getElementById("builder-profession").value = "";
  document.getElementById("builder-personality").value = "";
  document.getElementById("builder-style").value = "";
  document.getElementById("builder-notes").value = "";
  show("persona-builder-modal");
}

function previewPersona(personaId) {
  personaModalMode = "preview";
  api("/personas/" + personaId).then(function(data) {
    var editor = document.getElementById("persona-editor");
    editor.value = data.content || "";
    editor.readOnly = true;
    document.getElementById("persona-modal-title").textContent = "Persona: " + personaId.replace(/_/g, " ");
    document.getElementById("persona-name-row").classList.add("hidden");
    document.getElementById("persona-apply-btn").classList.add("hidden");
    document.getElementById("persona-save-server-btn").classList.add("hidden");
    show("persona-modal");
  }).catch(function() {
    toast("Could not load persona.");
  });
}

document.getElementById("persona-apply-btn").addEventListener("click", function() {
  var name = document.getElementById("persona-name").value.trim();
  var content = document.getElementById("persona-editor").value.trim();
  if (content && personaModalTarget) {
    gladiatorPersonas[personaModalTarget] = {
      persona_id: "__custom__",
      persona_name: name || extractPersonaNameFromContent(content) || "Custom Persona",
      persona_content: content
    };
    toast("Persona applied to this gladiator.");
  }
  hide("persona-modal");
  resetPersonaSelectValue(personaModalTarget);
});

document.getElementById("persona-save-server-btn").addEventListener("click", function() {
  var name = document.getElementById("persona-name").value.trim();
  var content = document.getElementById("persona-editor").value.trim();
  if (!name) return toast("Enter a name first.");
  if (!content) return toast("Write the persona content.");

  var pid = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
  api("/personas", {
    method: "POST",
    body: JSON.stringify({ persona_id: pid, content: content })
  }).then(function(meta) {
    toast("Saved: " + meta.name);
    // Apply to current gladiator too
    if (personaModalTarget) {
      gladiatorPersonas[personaModalTarget] = {
        persona_id: pid,
        persona_name: meta.name || name,
        persona_content: content
      };
    }
    // Refresh persona list
    fetchPersonas().then(function() { renderGladiatorGrid(); });
    hide("persona-modal");
  }).catch(function(e) {
    toast("Save failed: " + (e.message || ""));
  });
});

document.getElementById("persona-cancel").addEventListener("click", function() {
  hide("persona-modal");
  if (personaModalMode === "apply" && personaModalTarget && !gladiatorPersonas[personaModalTarget]) {
    resetPersonaSelectValue(personaModalTarget);
  }
});

document.getElementById("builder-generate-btn").addEventListener("click", function() {
  var profession = document.getElementById("builder-profession").value.trim();
  var personality = document.getElementById("builder-personality").value.trim();
  var style = document.getElementById("builder-style").value.trim();
  if (!profession) return toast("Enter your job or role first.");
  if (!personality) return toast("Describe your personality in a few words.");
  if (!style) return toast("Describe your debate style.");

  api("/personas/generate", {
    method: "POST",
    body: JSON.stringify({
      persona_name: document.getElementById("builder-persona-name").value.trim() || null,
      profession: profession,
      personality: personality,
      debate_style: style,
      free_text: document.getElementById("builder-notes").value.trim() || null
    })
  }).then(function(data) {
    hide("persona-builder-modal");
    openPersonaModalWithDraft(data.name || "", data.content || "", personaBuilderTarget);
    personaBuilderTarget = null;
    toast("Draft persona generated. Review and tweak it if needed.");
  }).catch(function(e) {
    toast("Could not generate persona: " + (e.message || ""));
  });
});

document.getElementById("builder-cancel").addEventListener("click", function() {
  hide("persona-builder-modal");
  resetPersonaSelectValue(personaBuilderTarget);
  personaBuilderTarget = null;
});

/* ── Build payload ── */
function buildProviderPayloadFromVariant(gladiatorId, variant, tier) {
  var provider = { type: variant.type, model: variant.model };
  provider.billing_tier = tier === "paid" ? "paid" : "free";
  if (variant.type === "huggingface_local") {
    var ollamaModel = variant.model.replace("ollama:", "");
    provider.ollama_model = ollamaModel;
    provider.hf_model = ollamaModel;
  }
  if (variant.type === "ollama") {
    provider.ollama_model = variant.model.replace("ollama:", "");
  }
  return provider;
}

function buildProviderPayloadFromCustomModel(model) {
  var rawModel = model.model || "";
  var normalizedModel = normalizeLocalModelId(rawModel);
  var provider = {
    type: model.type,
    model: model.model,
    billing_tier: model.tier === "paid" ? "paid" : "free"
  };
  if (model.command && model.command.length) provider.command = model.command;
  if (model.type === "ollama") {
    provider.ollama_model = normalizedModel;
    provider.model = "ollama:" + normalizedModel;
  } else if (model.type === "huggingface_local") {
    provider.hf_model = normalizedModel;
    provider.ollama_model = normalizedModel;
    provider.model = rawModel.indexOf("ollama:") === 0 || rawModel.indexOf("hf:") === 0 ? rawModel : "hf:" + normalizedModel;
  }
  return provider;
}

function findVariantByModel(modelId) {
  var found = null;
  GLADIATORS.some(function(g) {
    return (g.variants || []).some(function(v) {
      if (v.model === modelId) {
        found = { gladiator: g, variant: v };
        return true;
      }
      return false;
    });
  });
  if (found) return found;
  customModels.some(function(m) {
    if (m.model === modelId || ("ollama:" + m.model) === modelId || ("hf:" + m.model) === modelId) {
      found = { custom: true, model: m };
      return true;
    }
    return false;
  });
  return found;
}

function judgeModelOptions() {
  var options = [];
  GLADIATORS.forEach(function(g) {
    (g.variants || []).forEach(function(v, idx) {
      options.push({
        value: "builtin:" + g.id + ":" + idx,
        label: g.name + " — " + v.label + (g.tier === "paid" ? " · paid" : " · free"),
        tier: g.tier,
        entry: g,
        variant: v,
        blocked: false,
        custom: false
      });
    });
  });
  customModels.forEach(function(model) {
    options.push({
      value: "custom:" + model.id,
      label: model.name + (model.tier === "paid" ? " · paid" : " · free"),
      tier: model.tier,
      entry: model,
      blocked: false,
      custom: true,
      model: model
    });
  });
  return options;
}

function defaultJudgeModelValue(options) {
  var firstPaid = "";
  var firstAvailable = "";
  (options || []).forEach(function(option) {
    if (option.blocked) return;
    if (!firstAvailable) firstAvailable = option.value;
    if (!firstPaid && option.tier === "paid") firstPaid = option.value;
  });
  return firstPaid || firstAvailable || ((options && options[0]) ? options[0].value : "");
}

function getSelectedJudgeModelOption() {
  if (!judgeModelSelect) return null;
  return judgeModelIndex[judgeModelSelect.value] || null;
}

function renderJudgeModelOptions() {
  if (!judgeModelSelect) return;
  var options = judgeModelOptions();
  var previous = judgeModelSelect.value;
  judgeModelIndex = {};
  judgeModelSelect.innerHTML = "";
  if (!options.length) {
    judgeModelSelect.innerHTML = '<option value="">No models available</option>';
    judgeModelSelect.disabled = true;
    updateJudgeControls();
    return;
  }
  options.forEach(function(option) {
    judgeModelIndex[option.value] = option;
    var opt = document.createElement("option");
    opt.value = option.value;
    opt.textContent = option.label + (option.blocked ? " — unavailable" : "");
    opt.disabled = !!option.blocked;
    judgeModelSelect.appendChild(opt);
  });
  judgeModelSelect.disabled = false;
  var nextValue = previous && judgeModelIndex[previous] && !judgeModelIndex[previous].blocked
    ? previous
    : defaultJudgeModelValue(options);
  if (nextValue) judgeModelSelect.value = nextValue;
  updateJudgeControls();
}

function buildJudgeProviderPayload() {
  var option = getSelectedJudgeModelOption();
  if (!option) return null;
  return option.custom
    ? buildProviderPayloadFromCustomModel(option.model)
    : buildProviderPayloadFromVariant(option.entry.id, option.variant, option.entry.tier);
}

function validateJudgeSelection() {
  if (currentJudgeMode !== "ai") return true;
  var option = getSelectedJudgeModelOption();
  if (!option) {
    toast("Choose a model for the AI judge.");
    return false;
  }
  if (option.blocked) {
    toast(option.label + " cannot judge right now.");
    return false;
  }
  return true;
}

function buildPaidProviderPolicy() {
  return { on_exhaustion: "fail" };
}

function startPolicyNote() {
  var searchLine = encourageInternetSearch
    ? " Search-aware mode is on, so agents are encouraged to verify uncertain claims with authoritative web sources when their provider supports it."
    : " Search-aware mode is off, so agents must stay inside the frozen bundle and explicitly mark uncertainty.";
  return "Arena locked. Preparing shared context and scheduling gladiators..." + searchLine;
}

function buildPayload() {
  var topic = document.getElementById("topic").value.trim();
  var depth = parseInt(document.getElementById("depth").value);
  var topicType = document.getElementById("topic-type").value;
  var codebaseUrl = document.getElementById("codebase-url").value.trim();

  var agents = [];

  // Built-in gladiators
  GLADIATORS.forEach(function(g) {
    if (!selectedGladiators[g.id]) return;
    var vIdx = gladiatorVariants[g.id] || 0;
    var v = g.variants[vIdx];
    var persona = gladiatorPersonas[g.id];
    var agentObj = {
      agent_id: g.id,
      display_name: g.name + " (" + v.label + ")",
      specialty: g.name + " " + v.label,
      provider: buildProviderPayloadFromVariant(g.id, v, g.tier)
    };
    if (persona) {
      agentObj.persona_id = persona.persona_id;
      agentObj.persona_name = persona.persona_name;
      agentObj.persona_content = persona.persona_content;
    }
    agents.push(agentObj);
  });

  // Custom models
  customModels.forEach(function(m) {
    if (!selectedGladiators[m.id]) return;
    var persona = gladiatorPersonas[m.id];
    agents.push({
      agent_id: m.id,
      display_name: m.name,
      specialty: m.desc,
      provider: buildProviderPayloadFromCustomModel(m),
      persona_id: persona ? persona.persona_id : undefined,
      persona_name: persona ? persona.persona_name : undefined,
      persona_content: persona ? persona.persona_content : undefined
    });
  });

  var contextSources = [{
    source_id: "topic",
    kind: "inline_text",
    label: "Debate topic",
    content: topic
  }];

  if (codebaseUrl) {
    contextSources.push({
      source_id: "codebase-url",
      kind: "inline_text",
      label: "Codebase reference",
      content: "Codebase URL: " + codebaseUrl
    });
  }

  contextSources = contextSources.concat(attachedFiles.map(function(f, i) {
    var source = {
      source_id: "file-" + i,
      kind: f.kind || "inline_text",
      label: f.name,
      content: f.content
    };
    if ((f.kind || "inline_text") === "inline_image") {
      source.media_type = f.mediaType || guessImageMediaType(f.name);
      source.description = "Shared image uploaded through the Colosseum arena UI.";
    }
    return source;
  }));

  var judgeProvider = currentJudgeMode === "ai" ? buildJudgeProviderPayload() : null;

  var responseLang = document.getElementById("response-language").value;

  return {
    project_name: "Colosseum",
    encourage_internet_search: encourageInternetSearch,
    response_language: responseLang,
    task: {
      title: topic.length > 120 ? topic.slice(0, 120) : topic,
      problem_statement: topic + (codebaseUrl ? "\n\nCodebase: " + codebaseUrl : ""),
      task_type: topicType
    },
    context_sources: contextSources,
    agents: agents,
    judge: {
      mode: currentJudgeMode,
      provider: judgeProvider || undefined,
      minimum_confidence_to_stop: (DEPTH_PROFILES[depth] || DEPTH_PROFILES[3]).confidence,
      prefer_merged_plan_on_close_scores: true,
      use_evidence_based_judging: useEvidenceBasedJudging
    },
    paid_provider_policy: buildPaidProviderPolicy(),
    budget_policy: (function() {
      var t = timeoutNolimit.checked ? 0 : (parseInt(timeoutInput.value) || 0);
      var profile = DEPTH_PROFILES[depth] || DEPTH_PROFILES[3];
      return {
        max_rounds: depth,
        min_rounds: profile.min_rounds,
        total_token_budget: 80000,
        per_round_token_limit: 12000,
        per_agent_message_limit: 1,
        min_novelty_threshold: profile.min_novelty,
        convergence_threshold: profile.convergence,
        planning_timeout_seconds: t,
        round_timeout_seconds: t,
        late_round_timeout_factor: 0.8,
        min_round_timeout_seconds: 0,
        per_round_timeouts: []
      };
    })()
  };
}

/* ── Live mode helpers ── */
var liveRunData = { plans: [], plan_evaluations: [], debate_rounds: [], verdict: null, budget_by_actor: {} };

function appendLiveEntry(text, eventClass) {
  var log = document.getElementById("live-log");
  var entry = document.createElement("div");
  entry.className = "live-entry" + (eventClass ? " event-" + eventClass : "");
  entry.innerHTML = '<span class="live-time">' + timeStr() + '</span>' + esc(text);
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

function appendAgentThinking(name, message) {
  var log = document.getElementById("live-log");
  var entry = document.createElement("div");
  entry.className = "chat-thinking";
  entry.innerHTML = '<span class="agent-badge">' + esc(name) + '</span> ' +
    '<span class="thinking-dots">' + esc(message) + '</span>';
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

function appendAgentPlan(evt) {
  var log = document.getElementById("live-log");
  var entry = document.createElement("div");
  entry.className = "live-entry live-agent-plan";
  var strengthTags = (evt.strengths || []).slice(0, 2).map(function(s) {
    return '<span class="mini-tag">' + esc(s) + '</span>';
  }).join("");
  entry.innerHTML = '<span class="live-time">' + timeStr() + '</span>' +
    '<div class="agent-plan-card">' +
      '<div class="agent-plan-header">' +
        '<span class="agent-badge">' + esc(evt.display_name || evt.agent_id) + '</span>' +
        '<span class="plan-ready-label">Plan Ready</span>' +
      '</div>' +
      '<div class="agent-plan-summary">' + esc(evt.summary || "") + '</div>' +
      '<div class="agent-plan-tags">' + strengthTags + '</div>' +
    '</div>';
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

function appendAgentMessage(evt) {
  var log = document.getElementById("live-log");
  var entry = document.createElement("div");
  // Alternate alignment for debate feel
  var agentIdx = 0;
  var agents = Object.keys(liveRunData._agentOrder || {});
  var aid = evt.agent_id || evt.display_name || "";
  if (!liveRunData._agentOrder) liveRunData._agentOrder = {};
  if (!(aid in liveRunData._agentOrder)) {
    liveRunData._agentOrder[aid] = Object.keys(liveRunData._agentOrder).length;
  }
  agentIdx = liveRunData._agentOrder[aid];
  var side = agentIdx % 2 === 0 ? "left" : "right";
  entry.className = "chat-bubble chat-bubble-" + side;

  var fullContent = evt.content || "";
  var preview = fullContent.length > 400 ? fullContent.slice(0, 400) + "..." : fullContent;
  var tokens = evt.usage ? evt.usage.total_tokens : 0;
  var novelty = evt.novelty_score != null ? evt.novelty_score : "-";

  // Extract rebuttals and concessions for chat display
  var interactionHtml = "";
  if ((evt.critique_count || 0) > 0 || (evt.defense_count || 0) > 0 || (evt.concession_count || 0) > 0) {
    interactionHtml = '<div class="chat-interactions">';
    if (evt.critique_count > 0) interactionHtml += '<span class="stat-pill critique">Rebuttals: ' + evt.critique_count + '</span>';
    if (evt.defense_count > 0) interactionHtml += '<span class="stat-pill defense">Defenses: ' + evt.defense_count + '</span>';
    if (evt.concession_count > 0) interactionHtml += '<span class="stat-pill concession">Concessions: ' + evt.concession_count + '</span>';
    interactionHtml += '</div>';
  }

  entry.innerHTML =
    '<div class="chat-header">' +
      '<span class="agent-badge agent-badge-' + side + '">' + esc(evt.display_name || evt.agent_id) + '</span>' +
      '<span class="chat-meta">' +
        '<span class="chat-round">R' + (evt.round_index || "?") + '</span>' +
        '<span class="agent-tokens">' + tokens.toLocaleString() + ' tok</span>' +
      '</span>' +
    '</div>' +
    '<div class="chat-content">' + esc(preview) + '</div>' +
    interactionHtml +
    '<div class="chat-footer">' +
      '<span class="stat-pill novelty">Novelty: ' + (typeof novelty === "number" ? novelty.toFixed(2) : novelty) + '</span>' +
      '<span class="live-time">' + timeStr() + '</span>' +
    '</div>';

  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

function appendJudgeDecision(evt) {
  var log = document.getElementById("live-log");
  var entry = document.createElement("div");
  entry.className = "live-entry live-judge-decision";

  var action = evt.action || "unknown";
  var actionLabel = action === "finalize" ? "FINALIZE" :
                    action === "continue_debate" ? "CONTINUE" :
                    action === "request_revision" ? "REVISION" : action.toUpperCase();

  var html = '<span class="live-time">' + timeStr() + '</span>' +
    '<div class="judge-decision-card">' +
      '<div class="judge-decision-header">' +
        '<span class="judge-badge">Judge</span>' +
        '<span class="judge-action judge-action-' + esc(action) + '">' + esc(actionLabel) + '</span>' +
      '</div>' +
      (evt.agenda_title ? '<div class="judge-agenda-line"><strong>Issue:</strong> ' + esc(evt.agenda_title) + '</div>' : '') +
      (evt.agenda_question ? '<div class="judge-agenda-question">' + esc(evt.agenda_question) + '</div>' : '') +
      '<div class="judge-reasoning">' + esc(evt.reasoning || "") + '</div>' +
      '<div class="judge-stats">' +
        '<span class="stat-pill">Confidence: ' + (evt.confidence != null ? Number(evt.confidence).toFixed(2) : "-") + '</span>' +
        '<span class="stat-pill">Disagreement: ' + (evt.disagreement_level != null ? Number(evt.disagreement_level).toFixed(2) : "-") + '</span>' +
        '<span class="stat-pill">Budget: ' + (evt.budget_pressure != null ? (Number(evt.budget_pressure) * 100).toFixed(0) + "%" : "-") + '</span>' +
      '</div>' +
    '</div>';

  entry.innerHTML = html;
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

function handleSSEEvent(evt) {
  if (!evt || !evt.phase) return;
  var phase = evt.phase;

  if (phase === "init") {
    currentRunId = evt.run_id || currentRunId;
    liveRunData = { plans: [], plan_evaluations: [], debate_rounds: [], verdict: null, budget_by_actor: {}, _agentOrder: liveRunData._agentOrder || {} };
    appendLiveEntry("Debate arena opened. Run: " + (evt.run_id || "").slice(0, 8), "debate");
    setBattleNote("Run initialized. Freezing shared context for all participants.", true);
  } else if (phase === "context") {
    appendLiveEntry(evt.message || "Preparing context...", "plan");
    setBattleNote("Freezing and normalizing the shared context bundle...", true);
  } else if (phase === "planning") {
    appendLiveEntry(evt.message || "Generating plans...", "plan");
    setBattleNote("Generating independent plans. This is often the longest step with external CLIs.", true);
  } else if (phase === "agent_planning") {
    appendAgentThinking(evt.display_name || evt.agent_id, "Crafting strategy...");
  } else if (phase === "plan_ready") {
    appendAgentPlan(evt);
    liveRunData.plans.push(evt);
  } else if (phase === "plan_failed") {
    appendLiveEntry((evt.display_name || evt.agent_id) + " failed during planning: " + (evt.error || "timeout"), "plan-failed");
    setBattleNote((evt.display_name || "Agent") + " was eliminated from the debate.", true);
  } else if (phase === "single_agent_victory") {
    appendLiveEntry((evt.display_name || evt.agent_id) + " is the only survivor — debate skipped, automatic victory!", "eliminated");
    setBattleNote("Only one gladiator survived planning. Skipping debate.", true);
  } else if (phase === "plans_ready") {
    liveRunData.plans = evt.plans || [];
    liveRunData.plan_evaluations = evt.evaluations || [];
    var names = liveRunData.plans.map(function(p) { return p.display_name; }).join(", ");
    appendLiveEntry("All plans evaluated: " + names, "plan");
  } else if (phase === "human_required") {
    currentRunId = evt.run_id || currentRunId;
    appendLiveEntry("Human judge input required. Opening the full battle report...", "verdict");
    setBattleNote("Initial reports are ready. Moving to the report screen for judge-led issue selection.", false);
    window.setTimeout(function() { openReport(currentRunId); }, 500);
  } else if (phase === "debate_round") {
    // Show skip and cancel buttons
    skipRoundBtn.classList.remove("hidden");
    cancelDebateBtn.classList.remove("hidden");
    // Add round separator in debate view
    var log = document.getElementById("live-log");
    var sep = document.createElement("div");
    sep.className = "round-separator";
    var timeoutLabel = evt.timeout_seconds ? " · timeout " + Math.floor(evt.timeout_seconds / 60) + "m" + (evt.timeout_seconds % 60 ? evt.timeout_seconds % 60 + "s" : "") : " · no limit";
    sep.innerHTML = '<span class="round-sep-line"></span><span class="round-sep-label">Round ' +
      (evt.round_index || "?") + ': ' + esc(evt.round_type || "debate") + timeoutLabel + '</span><span class="round-sep-line"></span>';
    log.appendChild(sep);
    setBattleNote(
      "Debate round " + (evt.round_index || "") + " in progress on '" + (evt.agenda_title || evt.round_type || "the current issue") + "'." +
      (evt.timeout_seconds ? " (timeout: " + Math.floor(evt.timeout_seconds / 60) + "m)" : " (no time limit)"),
      true
    );
  } else if (phase === "agent_thinking") {
    appendAgentThinking(evt.display_name || evt.agent_id, "Thinking... (Round " + evt.round_index + ")");
  } else if (phase === "agent_message") {
    appendAgentMessage(evt);
  } else if (phase === "round_cancelled") {
    skipRoundBtn.classList.add("hidden");
    cancelDebateBtn.classList.add("hidden");
    appendLiveEntry("Round " + (evt.round_index || "?") + " cancelled (" + (evt.messages_collected || 0) + " messages collected)", "error");
  } else if (phase === "cancelled") {
    skipRoundBtn.classList.add("hidden");
    cancelDebateBtn.classList.add("hidden");
    appendLiveEntry("Debate cancelled by user.", "error");
    setBattleNote("Debate was cancelled.", false);
    if (currentRunId) {
      window.setTimeout(function() { openReport(currentRunId); }, 600);
    }

    var btn = document.getElementById("start-btn");
    btn.disabled = false;
    btn.textContent = "FIGHT!";
  } else if (phase === "round_skipped") {
    skipRoundBtn.classList.add("hidden");
    appendLiveEntry("Round " + (evt.round_index || "?") + " skipped (" + (evt.messages_collected || 0) + " messages collected before skip)", "skipped");
  } else if (phase === "round_complete" && evt.round) {
    skipRoundBtn.classList.add("hidden");
    liveRunData.debate_rounds.push(evt.round);
    var msgCount = evt.round.messages ? evt.round.messages.length : 0;
    appendLiveEntry("Round " + evt.round.index + " complete (" + msgCount + " messages, " + (evt.round.usage ? evt.round.usage.total_tokens : 0) + " tokens)", "debate");
  } else if (phase === "judge_decision") {
    appendJudgeDecision(evt);
  } else if (phase === "judging") {
    appendLiveEntry(evt.message || "Rendering final verdict...", "verdict");
    setBattleNote("Judge is synthesizing the final verdict and usage report...", true);
  } else if (phase === "synthesizing_report") {
    appendLiveEntry(evt.message || "Synthesizing executive report...", "verdict");
    setBattleNote("Generating executive report...", true);
  } else if (phase === "complete") {
    skipRoundBtn.classList.add("hidden");
    cancelDebateBtn.classList.add("hidden");
    liveRunData.verdict = evt.verdict || null;
    liveRunData.budget_by_actor = evt.budget_by_actor || {};
    liveRunData.final_report = evt.final_report || null;
    appendLiveEntry("Debate complete!", "verdict");

    if (currentRunId) {
      setBattleNote("Battle finished. Opening the full report...", false);
      window.setTimeout(function() { openReport(currentRunId); }, 600);
    } else {
      renderLiveResult();
    }
    var btn = document.getElementById("start-btn");
    btn.disabled = false;
    btn.textContent = "FIGHT!";
  } else if (phase === "error") {
    skipRoundBtn.classList.add("hidden");
    cancelDebateBtn.classList.add("hidden");
    appendLiveEntry("Error: " + (evt.message || "Unknown error"), "error");
    setBattleNote("The run ended with an error. Try reducing context size or switching to fewer models.", false);

  } else {
    appendLiveEntry(phase + (evt.message ? ": " + evt.message : ""), "debate");
  }
}

function renderLiveResult() {
  // Build a run-like object from accumulated SSE data
  var run = {
    plans: liveRunData.plans,
    plan_evaluations: liveRunData.plan_evaluations,
    debate_rounds: liveRunData.debate_rounds,
    verdict: liveRunData.verdict
  };
  renderPlans(run);
  renderDebate(run);
  renderVerdict(run);

  // Render usage from budget_by_actor
  var budgetByActor = liveRunData.budget_by_actor;
  var actorKeys = Object.keys(budgetByActor);
  if (actorKeys.length) {
    var maxTokens = 1;
    actorKeys.forEach(function(k) {
      var t = budgetByActor[k].total_tokens || 0;
      if (t > maxTokens) maxTokens = t;
    });

    var grid = document.getElementById("usage-grid");
    grid.innerHTML = actorKeys.map(function(k) {
      var u = budgetByActor[k];
      var total = u.total_tokens || 0;
      var pct = Math.round((total / maxTokens) * 100);
      var costVal = u.estimated_cost_usd || 0;
      var costHtml = costVal > 0 ? '<div class="usage-card-cost">$' + costVal.toFixed(4) + '</div>' : '';
      return '<div class="usage-card">' +
        '<div class="usage-card-name">' + esc(k) + '</div>' +
        '<div class="usage-card-total">' + total.toLocaleString() + costHtml + '</div>' +
        '<div class="usage-card-detail">' +
          'Prompt: ' + (u.prompt_tokens || 0).toLocaleString() + '<br>' +
          'Completion: ' + (u.completion_tokens || 0).toLocaleString() +
        '</div>' +
        '<div class="usage-bar-wrap"><div class="usage-bar" style="width:' + pct + '%"></div></div>' +
        '</div>';
    }).join("");
    show("usage-sec");
  }
}

function processSSEChunk(text) {
  var events = [];
  var lines = text.split("\n");
  var buffer = "";
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (line.indexOf("data: ") === 0) {
      buffer += line.slice(6);
    } else if (line === "" && buffer) {
      try {
        events.push(JSON.parse(buffer));
      } catch (e) {
        // not valid JSON, skip
      }
      buffer = "";
    }
  }
  // leftover
  if (buffer) {
    try {
      events.push(JSON.parse(buffer));
    } catch (e) { /* skip */ }
  }
  return events;
}

/* ── Start debate ── */
document.getElementById("start-btn").addEventListener("click", function() {
  var topic = document.getElementById("topic").value.trim();
  if (!topic) return toast("Enter a battle topic first.");

  var selectedCount = Object.keys(selectedGladiators).length;
  if (selectedCount < 2) return toast("Choose at least 2 gladiators.");
  if (!validateJudgeSelection()) return;

  var payload = buildPayload();
  var btn = document.getElementById("start-btn");
  btn.disabled = true;
  btn.textContent = "BATTLING...";
  setBattleNote(startPolicyNote(), true);

  // Reset result sections
  hide("plans-sec");
  hide("debate-sec");
  hide("verdict-sec");
  hide("usage-sec");

  if (currentMode === "live") {
    startLiveMode(payload, btn);
  } else {
    startResultMode(payload, btn);
  }
});

function startLiveMode(payload, btn) {
  // Transition: hide setup, show debate arena
  hide("setup");
  show("live-feed");
  document.getElementById("live-log").innerHTML = "";
  currentRunId = null;
  liveRunData._agentOrder = {};
  appendLiveEntry("The arena gates open... debate begins!", "debate");
  setBattleNote("Live mode is streaming progress. Real CLI providers may pause for tens of seconds between updates.", true);

  fetch("/runs/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  }).then(function(response) {
    if (!response.ok) {
      return response.json().catch(function() { return {}; }).then(function(b) {
        throw new Error(b.detail || "Stream request failed: " + response.status);
      });
    }

    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var sseBuffer = "";

    function readChunk() {
      return reader.read().then(function(result) {
        if (result.done) {
          appendLiveEntry("Stream ended.", "verdict");
          show("setup");
          btn.disabled = false;
          btn.textContent = "FIGHT!";
          setBattleNote("Debate finished. Review the full debate, strategies, and verdict below.", false);
          return;
        }

        sseBuffer += decoder.decode(result.value, { stream: true });

        // Process complete SSE messages
        var parts = sseBuffer.split("\n\n");
        // Keep the last part as buffer (might be incomplete)
        sseBuffer = parts.pop() || "";

        parts.forEach(function(part) {
          if (!part.trim()) return;
          var events = processSSEChunk(part + "\n\n");
          events.forEach(function(evt) {
            handleSSEEvent(evt);
          });
        });

        return readChunk();
      });
    }

    return readChunk();
	  }).catch(function(e) {
	    appendLiveEntry("Error: " + (e.message || "Connection failed"), "error");
	    show("setup");
	    if (currentRunId) {
	      appendLiveEntry("Stream disconnected. Recovering from the saved run artifact...", "debate");
	      setBattleNote("Live stream disconnected. Polling the existing run instead of starting a second one.", true);
	      recoverRun(currentRunId, btn);
	      return;
	    }
	    appendLiveEntry("Stream failed before a run id was confirmed. Falling back to results mode...", "debate");
	    setBattleNote("Live stream failed before initialization. Starting a results-only run once.", true);
	    startResultMode(payload, btn);
	  });
}

function startResultMode(payload, btn) {
  hide("live-feed");
  currentRunId = null;
  setBattleNote("Results-only mode waits for the full artifact. With real CLI providers this can take 30-180 seconds.", true);

  api("/runs", { method: "POST", body: JSON.stringify(payload) })
    .then(function(run) {
      currentRunId = run.run_id;
      if (run.status === "awaiting_human_judge") {
        toast("Opening the judge report.");
      } else {
        toast("Battle complete!");
      }
      setBattleNote("Opening the full battle report...", false);
      openReport(run.run_id);
    })
    .catch(function(e) {
      toast("Error: " + (e.message || "Failed to start battle."));
      setBattleNote("Battle failed before completion. Try a lighter model mix or smaller context.", false);
    })
    .then(function() {
      btn.disabled = false;
      btn.textContent = "FIGHT!";
    });
}

function recoverRun(runId, btn, attempt) {
  attempt = attempt || 0;
  api("/runs/" + encodeURIComponent(runId))
    .then(function(run) {
      currentRunId = run.run_id;
      if (run.status === "completed" || run.status === "failed" || run.status === "awaiting_human_judge") {
        if (run.status === "completed") {
          toast("Battle complete!");
          setBattleNote("Recovered the saved run. Opening the full report...", false);
          openReport(run.run_id);
        } else if (run.status === "awaiting_human_judge") {
          setBattleNote("Recovered the saved run. Opening the report for human judge actions.", false);
          openReport(run.run_id);
        } else {
          setBattleNote("Recovered the saved run, but it failed before completion. Opening the report.", false);
          openReport(run.run_id);
        }
        btn.disabled = false;
        btn.textContent = "FIGHT!";
        return;
      }

      setBattleNote("Recovering the saved run. The backend is still working; polling again shortly.", true);
      window.setTimeout(function() {
        recoverRun(runId, btn, attempt + 1);
      }, 2500);
    })
    .catch(function() {
      if (attempt >= 20) {
        btn.disabled = false;
        btn.textContent = "FIGHT!";
        setBattleNote("Could not recover the saved run automatically. Use Past Battles to reopen it without starting a duplicate run.", false);
        return;
      }
      window.setTimeout(function() {
        recoverRun(runId, btn, attempt + 1);
      }, 2500);
    });
}

/* ── Render results ── */
function renderResult(run) {
  renderPlans(run);
  renderDebate(run);
  renderUsage(run);
  renderRuntimeEvents(run);
  renderVerdict(run);
}

function renderRuntimeEvents(run) {
  var list = document.getElementById("events-list");
  if (!list) return;
  if (!run.runtime_events || !run.runtime_events.length) {
    hide("events-sec");
    return;
  }
  list.innerHTML = run.runtime_events.map(function(evt) {
    var meta = evt.provider_label ? esc(evt.provider_label) : esc(evt.actor_label || evt.actor_id);
    return '<div class="history-item">' +
      '<div>' +
        '<div class="history-title">' + meta + '</div>' +
        '<div class="history-meta">' + esc(evt.event_type) + '</div>' +
      '</div>' +
      '<div class="history-meta notice-copy">' + esc(evt.message) + '</div>' +
    '</div>';
  }).join("");
  show("events-sec");
}

function renderPlans(run) {
  if (!run.plans || !run.plans.length) return;
  var scores = {};
  (run.plan_evaluations || []).forEach(function(e) { scores[e.plan_id] = e.overall_score; });

  var el = document.getElementById("plans-grid");
  el.innerHTML = run.plans.map(function(p) {
    var evidenceTags = (p.evidence_basis || []).slice(0, 2).map(function(item) {
      return '<span class="tag evidence">' + esc(item) + '</span>';
    }).join("");
    var strengthTags = (p.strengths || []).slice(0, 2).map(function(s) {
      return '<span class="tag">' + esc(s) + '</span>';
    }).join("");
    var weakTags = (p.weaknesses || []).slice(0, 1).map(function(w) {
      return '<span class="tag weak">' + esc(w) + '</span>';
    }).join("");

    return '<div class="plan-card">' +
      '<h3>' + esc(p.display_name) + '</h3>' +
      '<span class="plan-score">Score ' + fmt(scores[p.plan_id]) + '</span>' +
      '<p>' + esc(p.summary) + '</p>' +
      (evidenceTags ? '<div class="plan-evidence"><strong>Evidence</strong><div class="tag-row">' + evidenceTags + '</div></div>' : '') +
      '<div class="tag-row">' + strengthTags + weakTags + '</div>' +
      '</div>';
  }).join("");

  show("plans-sec");
}

function renderDebate(run) {
  if (!run.debate_rounds || !run.debate_rounds.length) return;
  var el = document.getElementById("debate-timeline");

  el.innerHTML = run.debate_rounds.map(function(r) {
    var tokenCount = (r.usage && r.usage.total_tokens) ? r.usage.total_tokens + " tokens" : "";
    return '<div class="round-block">' +
      '<div class="round-head">' +
        '<h3>Round ' + r.index + ': ' + esc(r.round_type) + '</h3>' +
        '<span class="round-tag">' + tokenCount + '</span>' +
      '</div>' +
      '<div class="round-body">' +
        col("Key disagreements", r.summary ? r.summary.key_disagreements : []) +
        col("Strongest arguments", r.summary ? r.summary.strongest_arguments : []) +
        col("Hybrid ideas", r.summary ? r.summary.hybrid_opportunities : []) +
      '</div>' +
      '<div class="round-note">' + esc(r.summary ? (r.summary.moderator_note || "") : "") + '</div>' +
      '</div>';
  }).join("");

  show("debate-sec");
}

function renderUsage(run) {
  // Gather per-agent token usage from various sources
  var agentUsage = {};

  // From plans
  if (run.plans) {
    run.plans.forEach(function(p) {
      if (p.usage) {
        var key = p.agent_id || p.display_name || "Unknown";
        if (!agentUsage[key]) {
          agentUsage[key] = { name: p.display_name || key, total: 0, prompt: 0, completion: 0 };
        }
        agentUsage[key].total += (p.usage.total_tokens || 0);
        agentUsage[key].prompt += (p.usage.prompt_tokens || 0);
        agentUsage[key].completion += (p.usage.completion_tokens || 0);
      }
    });
  }

  // From debate rounds
  if (run.debate_rounds) {
    run.debate_rounds.forEach(function(r) {
      if (r.agent_usages) {
        r.agent_usages.forEach(function(au) {
          var key = au.agent_id || au.display_name || "Unknown";
          if (!agentUsage[key]) {
            agentUsage[key] = { name: au.display_name || key, total: 0, prompt: 0, completion: 0, cost: 0 };
          }
          agentUsage[key].total += (au.total_tokens || 0);
          agentUsage[key].prompt += (au.prompt_tokens || 0);
          agentUsage[key].completion += (au.completion_tokens || 0);
          agentUsage[key].cost += (au.estimated_cost_usd || 0);
        });
      }
    });
  }

  // From top-level usage
  if (run.agent_usages) {
    run.agent_usages.forEach(function(au) {
      var key = au.agent_id || au.display_name || "Unknown";
      agentUsage[key] = {
        name: au.display_name || key,
        total: au.total_tokens || 0,
        prompt: au.prompt_tokens || 0,
        completion: au.completion_tokens || 0,
        cost: au.estimated_cost_usd || 0
      };
    });
  }

  var keys = Object.keys(agentUsage);
  if (!keys.length) return;

  // Find max for bar scaling
  var maxTokens = 1;
  keys.forEach(function(k) {
    if (agentUsage[k].total > maxTokens) maxTokens = agentUsage[k].total;
  });

  var grid = document.getElementById("usage-grid");
  grid.innerHTML = keys.map(function(k) {
    var u = agentUsage[k];
    var pct = Math.round((u.total / maxTokens) * 100);
    var costHtml = u.cost > 0 ? '<div class="usage-card-cost">$' + u.cost.toFixed(4) + '</div>' : '';
    return '<div class="usage-card">' +
      '<div class="usage-card-name">' + esc(u.name) + '</div>' +
      '<div class="usage-card-total">' + u.total.toLocaleString() + costHtml + '</div>' +
      '<div class="usage-card-detail">' +
        'Prompt: ' + u.prompt.toLocaleString() + '<br>' +
        'Completion: ' + u.completion.toLocaleString() +
      '</div>' +
      '<div class="usage-bar-wrap"><div class="usage-bar" style="width:' + pct + '%"></div></div>' +
      '</div>';
  }).join("");

  show("usage-sec");
}

function renderVerdict(run) {
  if (!run.verdict) return;
  var v = run.verdict;
  var el = document.getElementById("verdict-body");

  var winnerNames = (v.winning_plan_ids || []).map(function(id) {
    var p = (run.plans || []).find(function(x) { return x.plan_id === id; });
    return p ? p.display_name : id.slice(0, 8);
  });

  var typeClass = v.verdict_type === "merged" ? "merged" : "winner";
  var html = '<span class="verdict-type ' + typeClass + '">' +
    esc(v.verdict_type ? v.verdict_type.toUpperCase() : 'UNKNOWN') + ': ' + esc(winnerNames.join(" & ")) + '</span>';

  html += '<div class="verdict-rationale">' + esc(v.rationale) + '</div>';
  html += '<div class="verdict-details">';

  if (v.selected_strengths && v.selected_strengths.length) {
    html += '<div class="verdict-col"><h4>Strengths</h4>' + ul(v.selected_strengths) + '</div>';
  }
  if (v.rejected_risks && v.rejected_risks.length) {
    html += '<div class="verdict-col"><h4>Risks Noted</h4>' + ul(v.rejected_risks) + '</div>';
  }
  if (v.synthesized_plan) {
    html += '<div class="verdict-col"><h4>Merged Plan</h4><p style="font-size:0.84rem;margin:0">' +
      esc(v.synthesized_plan.summary) + '</p></div>';
  }
  html += '</div>';
  html += '<div class="verdict-meta">Stop: ' + esc(v.stop_reason) + ' &middot; Confidence: ' + fmt(v.confidence) + '</div>';

  el.innerHTML = html;
  show("verdict-sec");
}

/* ── History ── */
document.getElementById("history-btn").addEventListener("click", function() {
  api("/runs")
    .then(function(runs) {
      var list = document.getElementById("history-list");
      if (!runs || !runs.length) {
        list.innerHTML = '<p class="muted">No battles fought yet.</p>';
      } else {
        list.innerHTML = runs.map(function(r) {
          return '<div class="history-item" data-id="' + esc(r.run_id) + '">' +
            '<div>' +
              '<div class="history-title">' + esc(r.task_title) + '</div>' +
              '<div class="history-meta">' + esc(r.status) + ' &middot; ' + esc(r.verdict_type || "pending") + '</div>' +
            '</div>' +
            '<div class="history-meta">' + (r.total_tokens || 0) + ' tok</div>' +
          '</div>';
        }).join("");

        list.querySelectorAll("[data-id]").forEach(function(item) {
          item.addEventListener("click", function() {
            openReport(item.dataset.id);
          });
        });
      }
    })
    .catch(function() { toast("Could not load history."); });
});
