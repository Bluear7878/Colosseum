function esc(v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmt(v) {
  return typeof v === "number" ? v.toFixed(2) : "-";
}

function toast(msg) {
  var el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(function() { el.classList.add("hidden"); }, 3200);
}

function show(id) {
  var el = document.getElementById(id);
  if (el) el.classList.remove("hidden");
}

function hide(id) {
  var el = document.getElementById(id);
  if (el) el.classList.add("hidden");
}

function api(path, opts) {
  opts = opts || {};
  return fetch(path, {
    method: opts.method || "GET",
    headers: Object.assign({ "Content-Type": "application/json" }, opts.headers || {}),
    body: opts.body || undefined
  }).then(function(r) {
    if (!r.ok) {
      return r.json().catch(function() { return {}; }).then(function(body) {
        throw new Error(body.detail || ("Request failed: " + r.status));
      });
    }
    return r.json();
  });
}

function runIdFromPath() {
  var parts = window.location.pathname.split("/").filter(Boolean);
  return parts.length ? decodeURIComponent(parts[parts.length - 1]) : "";
}

function list(items) {
  if (!items || !items.length) return "";
  return "<ul>" + items.map(function(item) {
    return "<li>" + esc(item) + "</li>";
  }).join("") + "</ul>";
}

function humanizePersonaId(personaId) {
  var cleaned = String(personaId || "").replace(/^_+|_+$/g, "").replace(/[_-]+/g, " ").trim();
  if (!cleaned) return "";
  return cleaned.replace(/\b[a-z]/g, function(ch) { return ch.toUpperCase(); });
}

function agentPersonaLabel(agent) {
  if (!agent) return "";
  if (agent.persona_label) return agent.persona_label;
  if (agent.persona_name) return agent.persona_name;
  if (agent.persona_id === "__custom__") return "Custom Persona";
  return humanizePersonaId(agent.persona_id);
}

function agentDisplayLabel(agent) {
  if (!agent) return "";
  if (agent.display_label) return agent.display_label;
  var base = agent.display_name || agent.agent_id || "";
  var persona = agentPersonaLabel(agent);
  if (!persona || base.toLowerCase().indexOf(persona.toLowerCase()) !== -1) return base;
  return base + " [" + persona + "]";
}

function planDisplayLabel(run, plan) {
  var agent = (run.agents || []).find(function(item) { return item.agent_id === plan.agent_id; }) || null;
  return agent ? agentDisplayLabel(agent) : (plan.display_name || plan.agent_id || "");
}

function claimList(title, claims, className) {
  if (!claims || !claims.length) return "";
  return '<div class="report-claim-group ' + esc(className || "") + '">' +
    '<h4>' + esc(title) + '</h4>' +
    '<ul>' + claims.map(function(claim) {
      var evidence = (claim.evidence || []).length
        ? '<div class="report-claim-evidence">Evidence: ' + esc((claim.evidence || []).join(" | ")) + '</div>'
        : '';
      return '<li><div class="report-claim-text">' + esc(claim.text || claim) + '</div>' + evidence + '</li>';
    }).join("") +
    '</ul></div>';
}

function plainList(title, items, className) {
  if (!items || !items.length) return "";
  return '<div class="report-claim-group ' + esc(className || "") + '">' +
    '<h4>' + esc(title) + '</h4>' + list(items) + '</div>';
}

function selectedPlanIds() {
  return Array.prototype.slice.call(document.querySelectorAll('.judge-plan-checkbox:checked')).map(function(el) {
    return el.value;
  });
}

function syncJudgeForm() {
  var action = document.getElementById("judge-action-select").value;
  var roundTypeWrap = document.getElementById("judge-round-type").parentNode;
  var picks = document.getElementById("judge-plan-picks");
  if (action === "request_round" || action === "request_revision") {
    roundTypeWrap.style.display = "";
  } else {
    roundTypeWrap.style.display = "none";
  }
  if (action === "select_winner" || action === "merge_plans") {
    picks.classList.remove("judge-plan-picks-muted");
  } else {
    picks.classList.add("judge-plan-picks-muted");
  }
}

// ─── Hero: status + run metrics ─────────────────────────────────────────────

function renderHero(run) {
  var title = document.getElementById("report-subtitle");
  if (title) {
    title.textContent = run.task.title + " · " + run.run_id.slice(0, 8);
  }

  var el = document.getElementById("hero-content");
  if (!el) return;

  var statusCopy = {
    completed: "Battle complete",
    awaiting_human_judge: "Waiting for the judge",
    failed: "Battle failed",
    planning: "Still planning",
    debating: "Debate in progress",
    pending: "Pending"
  };

  el.innerHTML =
    '<div class="report-hero-top">' +
      '<div>' +
        '<div class="eyebrow">Status</div>' +
        '<h2 class="report-title">' + esc(statusCopy[run.status] || run.status) + '</h2>' +
        (run.stop_reason ? '<p class="report-copy muted">' + esc(run.stop_reason) + '</p>' : '') +
      '</div>' +
      '<div class="hero-metrics">' +
        '<div class="hero-metric"><span class="hero-metric-label">Agents</span><strong>' + (run.agents || []).length + '</strong></div>' +
        '<div class="hero-metric"><span class="hero-metric-label">Rounds</span><strong>' + (run.debate_rounds || []).length + '</strong></div>' +
        '<div class="hero-metric"><span class="hero-metric-label">Tokens</span><strong>' + (((run.budget_ledger || {}).total || {}).total_tokens || 0).toLocaleString() + '</strong></div>' +
        (function() {
          var cost = (((run.budget_ledger || {}).total || {}).estimated_cost_usd || 0);
          return cost > 0 ? '<div class="hero-metric"><span class="hero-metric-label">Cost</span><strong>$' + cost.toFixed(4) + '</strong></div>' : '';
        })() +
      '</div>' +
    '</div>';
}

// ─── Debate Conclusion ───────────────────────────────────────────────────────

function renderDebateConclusion(run) {
  var fr = run.final_report;
  var verdict = run.verdict;

  if (!verdict && !fr) return;
  show("debate-conclusion");

  // One-line verdict headline
  var headlineText = (fr && (fr.one_line_verdict || fr.final_answer)) || "";
  if (!headlineText && verdict) {
    var winnerName = winnerDisplayName(run);
    if (winnerName && verdict.verdict_type === "merged") {
      headlineText = "Merged recommendation from " + winnerName + " — " + (verdict.rationale || "");
    } else if (winnerName) {
      headlineText = winnerName + " wins — " + (verdict.rationale || "");
    } else {
      headlineText = verdict.rationale || "";
    }
  }
  if (headlineText) {
    var headlineEl = document.getElementById("conclusion-headline");
    if (headlineEl) {
      headlineEl.textContent = headlineText;
      headlineEl.classList.remove("hidden");
    }
  }

  // Hallucination warnings
  renderHallucinationWarnings(run);

  // Verdict banner
  renderVerdictBanner(run);

  // Final report cards
  renderFinalReport(run);

  // Per-agent opinions
  renderAgentOpinions(run);
}

function winnerDisplayNames(run) {
  var verdict = run.verdict;
  if (!verdict || !verdict.winning_plan_ids || !verdict.winning_plan_ids.length) return [];
  return verdict.winning_plan_ids.map(function(wid) {
    var match = (run.plans || []).find(function(p) { return p.plan_id === wid; });
    return match ? planDisplayLabel(run, match) : wid.slice(0, 8);
  }).filter(Boolean);
}

function winnerDisplayName(run) {
  var names = winnerDisplayNames(run);
  if (!names.length) return "";
  if (run.verdict && run.verdict.verdict_type === "merged") {
    return names.join(" + ");
  }
  return names[0];
}

function renderVerdictBanner(run) {
  var el = document.getElementById("verdict-banner-section");
  if (!el) return;

  var verdict = run.verdict;
  if (verdict) {
    var winnerName = winnerDisplayName(run);
    var verdictLabel = winnerName || (verdict.verdict_type === "merged" ? "Merged recommendation" : "No winner");
    el.innerHTML =
      '<div class="report-verdict-banner">' +
        '<span class="verdict-type ' + esc(verdict.verdict_type || "winner") + '">' + esc((verdict.verdict_type || "winner").toUpperCase()) + '</span>' +
        '<div class="report-verdict-main">' + esc(verdictLabel) + '</div>' +
        '<div class="report-verdict-sub">' + esc(verdict.rationale || "") + '</div>' +
        '<div class="report-verdict-meta">Confidence ' + fmt(verdict.confidence) + '</div>' +
      '</div>';
  } else if (run.status === "awaiting_human_judge" && run.human_judge_packet) {
    el.innerHTML =
      '<div class="report-verdict-banner pending">' +
        '<span class="verdict-type pending">HUMAN JUDGE</span>' +
        '<div class="report-verdict-main">Choose the next issue or finalize</div>' +
        '<div class="report-verdict-sub">' + esc((run.human_judge_packet || {}).recommended_action || "") + '</div>' +
      '</div>';
  }
}

function renderFinalReport(run) {
  var el = document.getElementById("final-report-content");
  if (!el || !run.final_report) return;
  var fr = run.final_report;
  var html = '';

  if (fr.final_answer) {
    html += '<div class="conclusion-card conclusion-card-full">' +
      '<div class="conclusion-card-label">질문에 대한 최종 답변</div>' +
      '<p class="report-copy">' + esc(fr.final_answer) + '</p>' +
    '</div>';
  }
  if (fr.executive_summary) {
    html += '<div class="conclusion-card conclusion-card-full">' +
      '<div class="conclusion-card-label">판사의 종합 판결</div>' +
      '<p class="report-copy">' + esc(fr.executive_summary) + '</p>' +
    '</div>';
  }
  if (fr.verdict_explanation) {
    html += '<div class="conclusion-card">' +
      '<div class="conclusion-card-label">판결 근거</div>' +
      '<p class="report-copy">' + esc(fr.verdict_explanation) + '</p>' +
    '</div>';
  }
  if (fr.key_conclusions && fr.key_conclusions.length) {
    html += '<div class="conclusion-card">' +
      '<div class="conclusion-card-label">핵심 결론</div>' +
      list(fr.key_conclusions) +
    '</div>';
  }
  if (fr.debate_highlights && fr.debate_highlights.length) {
    html += '<div class="conclusion-card">' +
      '<div class="conclusion-card-label">토론 하이라이트</div>' +
      list(fr.debate_highlights) +
    '</div>';
  }
  if (fr.recommendations && fr.recommendations.length) {
    html += '<div class="conclusion-card">' +
      '<div class="conclusion-card-label">권고사항</div>' +
      list(fr.recommendations) +
    '</div>';
  }

  el.innerHTML = html;
}

// ─── Per-agent opinion breakdown ─────────────────────────────────────────────

function renderAgentOpinions(run) {
  var rounds = run.debate_rounds || [];
  var agents = run.agents || [];
  if (!rounds.length || !agents.length) return;

  // Build per-agent adopted arguments map
  var adopted = {}; // agent_id -> list of { summary, round }
  var agentNames = {};
  agents.forEach(function(a) {
    agentNames[a.agent_id] = a.display_name;
    adopted[a.agent_id] = [];
  });

  // Collect raised claims per message, and which messages had adoptions
  var adoptedMsgIds = {}; // message_id -> true
  rounds.forEach(function(round) {
    var adj = round.adjudication || {};
    (adj.adopted_arguments || []).forEach(function(arg) {
      if (adopted[arg.agent_id] !== undefined) {
        adopted[arg.agent_id].push({ summary: arg.summary, round: round.index, kind: arg.claim_kind });
      }
      adoptedMsgIds[arg.source_message_id] = true;
    });
  });

  // Build per-agent not-adopted claims
  var notAdopted = {}; // agent_id -> list of { text, round }
  agents.forEach(function(a) { notAdopted[a.agent_id] = []; });
  rounds.forEach(function(round) {
    (round.messages || []).forEach(function(msg) {
      if (!notAdopted[msg.agent_id] && !adopted[msg.agent_id]) return;
      // Only show claims from messages that had no adoptions
      if (adoptedMsgIds[msg.message_id]) return;
      var claims = (msg.critique_points || []).concat(msg.defense_points || []);
      claims.slice(0, 2).forEach(function(claim) {
        if (notAdopted[msg.agent_id]) {
          notAdopted[msg.agent_id].push({ text: claim.text || String(claim), round: round.index });
        }
      });
    });
  });

  var hasOpinions = agents.some(function(a) {
    return adopted[a.agent_id].length > 0 || notAdopted[a.agent_id].length > 0;
  });
  if (!hasOpinions) return;

  var winnerIds = (run.verdict && run.verdict.winning_plan_ids) ? run.verdict.winning_plan_ids : [];

  var html = agents.map(function(agent) {
    var isWinner = winnerIds.indexOf(agent.plan_id) !== -1;
    // Find the plan for this agent
    var plan = (run.plans || []).find(function(p) { return p.agent_id === agent.agent_id; });
    var planId = plan ? plan.plan_id : "";
    isWinner = winnerIds.indexOf(planId) !== -1;

    var adoptedArgs = adopted[agent.agent_id] || [];
    var notAdoptedArgs = notAdopted[agent.agent_id] || [];

    var adoptedHtml = adoptedArgs.length
      ? '<div class="agent-opinion-section adopted-section">' +
          '<div class="agent-opinion-section-label adopted-label">채택됨 (' + adoptedArgs.length + ')</div>' +
          '<ul>' + adoptedArgs.map(function(a) {
            return '<li><span class="adopted-tag">' + esc(a.kind || '') + '</span> ' + esc(a.summary) + ' <span class="muted">R' + a.round + '</span></li>';
          }).join('') + '</ul>' +
        '</div>'
      : '<div class="agent-opinion-section adopted-section"><div class="agent-opinion-section-label muted">채택된 의견 없음</div></div>';

    var notAdoptedHtml = notAdoptedArgs.length
      ? '<div class="agent-opinion-section not-adopted-section">' +
          '<div class="agent-opinion-section-label not-adopted-label">미채택 (' + notAdoptedArgs.length + ')</div>' +
          '<ul class="muted">' + notAdoptedArgs.slice(0, 3).map(function(a) {
            return '<li>' + esc(a.text) + ' <span class="muted">R' + a.round + '</span></li>';
          }).join('') + '</ul>' +
        '</div>'
      : '';

    return '<div class="agent-opinion-card' + (isWinner ? ' agent-opinion-winner' : '') + '">' +
      '<div class="agent-opinion-head">' +
        '<span class="agent-badge">' + esc(agentDisplayLabel(agent)) + '</span>' +
        (isWinner ? '<span class="winner-crown">👑 Winner</span>' : '') +
      '</div>' +
      adoptedHtml +
      notAdoptedHtml +
    '</div>';
  }).join('');

  var grid = document.getElementById("agent-opinions-grid");
  if (grid) {
    grid.innerHTML = html;
    show("agent-opinions");
  }
}

// ─── Hallucination warnings ───────────────────────────────────────────────────

function renderHallucinationWarnings(run) {
  var rounds = run.debate_rounds || [];
  var flags = [];
  rounds.forEach(function(round) {
    var adj = round.adjudication || {};
    (adj.hallucination_flags || []).forEach(function(flag) {
      flags.push({ round: round.index, flag: flag, kind: 'credibility' });
    });
    (adj.drift_flags || []).forEach(function(flag) {
      flags.push({ round: round.index, flag: flag, kind: 'drift' });
    });
  });
  if (!flags.length) return;

  var list = document.getElementById("hallucination-list");
  if (!list) return;
  list.innerHTML = flags.map(function(f) {
    var label = f.kind === 'drift' ? 'Off-topic' : 'Credibility';
    return '<div class="hallucination-flag">' +
      '<span class="hallucination-round">Round ' + f.round + ' · ' + label + '</span> ' +
      esc(f.flag) +
    '</div>';
  }).join('');
  show("hallucination-section");
}

// ─── Plans (collapsible) ──────────────────────────────────────────────────────

function renderPlans(run) {
  var el = document.getElementById("report-plans-grid");
  if (!el || !run.plans || !run.plans.length) return;
  var scores = {};
  (run.plan_evaluations || []).forEach(function(item) {
    scores[item.plan_id] = item.overall_score;
  });
  el.innerHTML = run.plans.map(function(plan) {
    return '<article class="plan-card report-plan-card">' +
      '<div class="report-plan-head">' +
        '<h3>' + esc(planDisplayLabel(run, plan)) + '</h3>' +
        '<span class="plan-score">Score ' + fmt(scores[plan.plan_id]) + '</span>' +
      '</div>' +
      '<p>' + esc(plan.summary || "") + '</p>' +
      plainList("Evidence basis", plan.evidence_basis || [], "evidence") +
      plainList("Architecture", plan.architecture || [], "architecture") +
      plainList("Implementation", plan.implementation_strategy || [], "implementation") +
      plainList("Strengths", plan.strengths || [], "strengths") +
      plainList("Weaknesses", plan.weaknesses || [], "weaknesses") +
      '</article>';
  }).join("");
  show("plans-report");
}

// ─── Timeline (collapsible) ───────────────────────────────────────────────────

function renderTimeline(run) {
  var el = document.getElementById("report-timeline");
  if (!el || !run.debate_rounds || !run.debate_rounds.length) return;

  var agentNames = {};
  (run.agents || []).forEach(function(agent) {
    agentNames[agent.agent_id] = agentDisplayLabel(agent);
  });

  el.innerHTML = run.debate_rounds.map(function(round) {
    var agenda = round.agenda || {};
    var adjudication = round.adjudication || {};
    var adoptedByMessage = {};
    (adjudication.adopted_arguments || []).forEach(function(item) {
      if (!item.source_message_id) return;
      if (!adoptedByMessage[item.source_message_id]) adoptedByMessage[item.source_message_id] = [];
      adoptedByMessage[item.source_message_id].push(item);
    });

    var messagesHtml = (round.messages || []).map(function(message) {
      var adopted = adoptedByMessage[message.message_id] || [];
      return '<article class="report-message-card">' +
        '<div class="report-message-head">' +
          '<span class="agent-badge">' + esc(agentNames[message.agent_id] || message.agent_id) + '</span>' +
          '<span class="round-tag">Novelty ' + fmt(message.novelty_score) + '</span>' +
        '</div>' +
        '<div class="report-message-content">' + esc(message.content || "") + '</div>' +
        (adopted.length ? '<div class="adopted-inline">' + adopted.map(function(item) {
          return '<span class="mini-tag adopted">Adopted ' + esc(item.claim_kind) + '</span>';
        }).join("") + '</div>' : '') +
        claimList("Critiques", message.critique_points || [], "critique") +
        claimList("Defenses", message.defense_points || [], "defense") +
        plainList("Concessions", message.concessions || [], "concession") +
        plainList("Hybrid suggestions", message.hybrid_suggestions || [], "hybrid") +
      '</article>';
    }).join("");

    var adoptedHtml = (adjudication.adopted_arguments || []).length
      ? '<div class="report-adoption-list">' + (adjudication.adopted_arguments || []).map(function(item) {
          return '<article class="report-adoption-card">' +
            '<div class="report-adoption-head">' +
              '<span class="agent-badge">' + esc(item.display_name || item.agent_id) + '</span>' +
              '<span class="round-tag">' + esc(item.claim_kind) + '</span>' +
            '</div>' +
            '<div class="report-adoption-summary">' + esc(item.summary || "") + '</div>' +
            ((item.evidence || []).length ? '<div class="report-claim-evidence">Evidence: ' + esc(item.evidence.join(" | ")) + '</div>' : '') +
            '<div class="report-adoption-reason">' + esc(item.adoption_reason || "") + '</div>' +
          '</article>';
        }).join("") + '</div>'
      : '<p class="muted">No argument was formally adopted in this round.</p>';

    // Hallucination + drift flags for this round
    var hallucinationItems = (adjudication.hallucination_flags || []).map(function(f) {
      return '<div class="hallucination-flag">' + esc(f) + '</div>';
    });
    var driftItems = (adjudication.drift_flags || []).map(function(f) {
      return '<div class="hallucination-flag">[Off-topic] ' + esc(f) + '</div>';
    });
    var allFlagItems = hallucinationItems.concat(driftItems);
    var flagsHtml = allFlagItems.length
      ? '<div class="report-side-block">' +
          '<h4>Credibility Alerts</h4>' +
          allFlagItems.join('') +
        '</div>'
      : '';

    return '<section class="report-round">' +
      '<div class="report-round-head">' +
        '<div>' +
          '<div class="eyebrow">Round ' + round.index + '</div>' +
          '<h3>' + esc(agenda.title || round.round_type || "Debate round") + '</h3>' +
          '<p class="report-copy">' + esc(agenda.question || round.purpose || "") + '</p>' +
        '</div>' +
        '<div class="round-tag">' + (((round.usage || {}).total_tokens) || 0).toLocaleString() + ' tok</div>' +
      '</div>' +
      (agenda.why_it_matters ? '<div class="report-round-why"><strong>Why it mattered:</strong> ' + esc(agenda.why_it_matters) + '</div>' : '') +
      '<div class="report-round-grid">' +
        '<div class="report-round-main">' + messagesHtml + '</div>' +
        '<aside class="report-round-side">' +
          '<div class="report-side-block"><h4>Judge adopted</h4>' + adoptedHtml + '</div>' +
          '<div class="report-side-block"><h4>Round summary</h4>' +
            plainList("Key disagreements", (round.summary || {}).key_disagreements || []) +
            plainList("Strongest arguments", (round.summary || {}).strongest_arguments || []) +
            plainList("Unresolved", adjudication.unresolved_points || (round.summary || {}).unresolved_questions || []) +
          '</div>' +
          (adjudication.resolution ? '<div class="report-side-block"><h4>Judge resolution</h4><p class="report-copy">' + esc(adjudication.resolution) + '</p><p class="muted">' + esc(adjudication.judge_note || "") + '</p></div>' : '') +
          flagsHtml +
        '</aside>' +
      '</div>' +
      '</section>';
  }).join("");
  show("timeline-report");
}

// ─── Usage ───────────────────────────────────────────────────────────────────

function renderUsage(run) {
  var el = document.getElementById("report-usage-grid");
  var byActor = ((run.budget_ledger || {}).by_actor) || {};
  var keys = Object.keys(byActor);
  if (!el || !keys.length) return;
  var labels = {};
  (run.agents || []).forEach(function(agent) {
    labels[agent.agent_id] = agent.display_name;
  });
  var maxTokens = 1;
  keys.forEach(function(key) {
    var total = (byActor[key] || {}).total_tokens || 0;
    if (total > maxTokens) maxTokens = total;
  });
  el.innerHTML = keys.map(function(key) {
    var usage = byActor[key] || {};
    var total = usage.total_tokens || 0;
    var pct = Math.round((total / maxTokens) * 100);
    var costVal = usage.estimated_cost_usd || 0;
    var costHtml = costVal > 0 ? '<div class="usage-card-cost">$' + costVal.toFixed(4) + '</div>' : '';
    return '<div class="usage-card">' +
      '<div class="usage-card-name">' + esc(labels[key] || key) + '</div>' +
      '<div class="usage-card-total">' + total.toLocaleString() + costHtml + '</div>' +
      '<div class="usage-card-detail">Prompt: ' + (usage.prompt_tokens || 0).toLocaleString() + '<br>Completion: ' + (usage.completion_tokens || 0).toLocaleString() + '</div>' +
      '<div class="usage-bar-wrap"><div class="usage-bar" style="width:' + pct + '%"></div></div>' +
    '</div>';
  }).join("");
  show("usage-report");
}

// ─── Events ──────────────────────────────────────────────────────────────────

function renderEvents(run) {
  var el = document.getElementById("report-events-list");
  if (!el || !run.runtime_events || !run.runtime_events.length) return;
  el.innerHTML = run.runtime_events.map(function(evt) {
    return '<div class="history-item">' +
      '<div><div class="history-title">' + esc(evt.actor_label || evt.actor_id) + '</div><div class="history-meta">' + esc(evt.event_type) + '</div></div>' +
      '<div class="history-meta notice-copy">' + esc(evt.message || "") + '</div>' +
      '</div>';
  }).join("");
  show("events-report");
}

// ─── Human judge panel ───────────────────────────────────────────────────────

function renderHumanPanel(run) {
  var panel = document.getElementById("human-judge-panel");
  if (!panel) return;
  if (run.status !== "awaiting_human_judge" || !run.human_judge_packet) {
    hide("human-judge-panel");
    return;
  }

  var packet = run.human_judge_packet;
  document.getElementById("human-judge-copy").innerHTML =
    '<p class="report-copy">' + esc(packet.recommended_action || "") + '</p>' +
    plainList("Key disagreements", packet.key_disagreements || []) +
    plainList("Strongest arguments so far", packet.strongest_arguments || []);

  document.getElementById("human-agenda").innerHTML = packet.suggested_agenda
    ? '<div class="report-side-block"><h4>Suggested next issue</h4><div class="report-adoption-summary">' +
      esc(packet.suggested_agenda.title || "") + '</div><p class="report-copy">' +
      esc(packet.suggested_agenda.question || "") + '</p></div>'
    : '';

  document.getElementById("judge-plan-picks").innerHTML = (run.plans || []).map(function(plan, idx) {
    return '<label class="judge-plan-option">' +
      '<input class="judge-plan-checkbox" type="checkbox" value="' + esc(plan.plan_id) + '"' + (idx < 2 ? ' checked' : '') + '/>' +
      '<span>' + esc(plan.display_name) + '</span>' +
      '</label>';
  }).join("");

  syncJudgeForm();
  show("human-judge-panel");
}

// ─── Report downloads ────────────────────────────────────────────────────────

function setupDownloadButton(run, config) {
  var btn = document.getElementById(config.id);
  if (!btn) return;
  if (run.status === "completed" || run.status === "failed") {
    btn.classList.remove("hidden");
    btn.onclick = function() {
      btn.disabled = true;
      btn.textContent = config.loadingText;
      fetch("/runs/" + encodeURIComponent(run.run_id) + config.path)
        .then(function(r) {
          if (!r.ok) throw new Error(config.errorPrefix + ": " + r.status);
          return r.blob();
        })
        .then(function(blob) {
          var url = URL.createObjectURL(blob);
          var a = document.createElement("a");
          a.href = url;
          a.download = "colosseum-report-" + run.run_id.slice(0, 8) + config.extension;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        })
        .catch(function(err) {
          toast(err.message || config.fallbackError);
        })
        .then(function() {
          btn.disabled = false;
          btn.textContent = config.defaultText;
        });
    };
  } else {
    btn.classList.add("hidden");
  }
}

function setupReportDownloads(run) {
  setupDownloadButton(run, {
    id: "download-pdf-btn",
    path: "/pdf",
    extension: ".pdf",
    defaultText: "Download PDF",
    loadingText: "Generating PDF...",
    errorPrefix: "PDF generation failed",
    fallbackError: "PDF download failed."
  });
  setupDownloadButton(run, {
    id: "download-md-btn",
    path: "/markdown",
    extension: ".md",
    defaultText: "Download Markdown",
    loadingText: "Generating Markdown...",
    errorPrefix: "Markdown generation failed",
    fallbackError: "Markdown download failed."
  });
}

// ─── Master render ────────────────────────────────────────────────────────────

function renderRun(run) {
  hide("debate-conclusion");
  hide("plans-report");
  hide("timeline-report");
  hide("usage-report");
  hide("events-report");
  renderHero(run);
  renderHumanPanel(run);
  renderDebateConclusion(run);
  renderPlans(run);
  renderTimeline(run);
  renderUsage(run);
  renderEvents(run);
  setupReportDownloads(run);
}

// ─── Bootstrap ────────────────────────────────────────────────────────────────

function loadRun() {
  var runId = runIdFromPath();
  if (!runId) {
    toast("Missing run id.");
    return;
  }
  api("/runs/" + encodeURIComponent(runId))
    .then(function(run) {
      renderRun(run);
      document.getElementById("judge-submit-btn").onclick = function() {
        submitJudgeAction(run.run_id);
      };
    })
    .catch(function(err) {
      document.getElementById("hero-content").innerHTML = '<div class="report-copy">Could not load run: ' + esc(err.message || "Unknown error") + '</div>';
    });
}

function submitJudgeAction(runId) {
  var action = document.getElementById("judge-action-select").value;
  var roundType = document.getElementById("judge-round-type").value;
  var winningIds = selectedPlanIds();
  var instructions = document.getElementById("judge-instructions").value.trim();

  if (action === "select_winner" && winningIds.length < 1) {
    toast("Choose one winning plan.");
    return;
  }
  if (action === "merge_plans" && winningIds.length < 2) {
    toast("Choose at least two plans to merge.");
    return;
  }

  var payload = {
    action: action,
    instructions: instructions || null
  };
  if (action === "request_round" || action === "request_revision") {
    payload.round_type = roundType;
  }
  if (action === "select_winner" || action === "merge_plans") {
    payload.winning_plan_ids = winningIds;
  }

  var btn = document.getElementById("judge-submit-btn");
  btn.disabled = true;
  btn.textContent = "Submitting...";
  api("/runs/" + encodeURIComponent(runId) + "/judge-actions", {
    method: "POST",
    body: JSON.stringify(payload)
  }).then(function(updated) {
    toast("Judge action applied.");
    renderRun(updated);
  }).catch(function(err) {
    toast(err.message || "Judge action failed.");
  }).then(function() {
    btn.disabled = false;
    btn.textContent = "Submit Judge Action";
  });
}

var judgeSelect = document.getElementById("judge-action-select");
if (judgeSelect) {
  judgeSelect.addEventListener("change", syncJudgeForm);
}
loadRun();
