"use strict";

const byId = (id) => document.getElementById(id);
const selectAll = (selector) => [...document.querySelectorAll(selector)];
const value = (id, text) => { byId(id).textContent = text; };
const pageSize = 30;
const states = { queued: "Queued", running: "Processing", done: "Completed", review: "Needs review", failed: "Failed" };
const auditLabels = {
  "workflow.saved": "Workflow saved", "job.created": "Job created", "job.resumed": "Job resumed",
  "job.paused": "Job paused", "item.claimed": "Record claimed", "item.done": "Record completed",
  "item.review": "Review requested", "item.reviewed": "Review saved", "item.failed": "Record failed",
  "item.requeued": "Interrupted record requeued", "item.recovery_exhausted": "Recovery attempts exhausted",
};
const state = {
  code: sessionStorage.getItem("autodialer-code") || "",
  view: "jobs", jobs: [], job: null, page: 0, revision: null, audit: [], review: null,
  listSignature: null, recordsSignature: null, refreshId: 0, audioUrl: null, androidUrl: null,
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function button(text, action) {
  const node = element("button", text, "button");
  node.type = "button";
  node.addEventListener("click", () => run(action, node));
  return node;
}

async function api(path, options = {}) {
  const headers = { "X-AutoDialer-Client": "web", ...options.headers };
  if (state.code) headers["X-AutoDialer-Code"] = state.code;
  const response = await fetch(`/api/${path}`, { ...options, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail) ? body.detail[0]?.msg : body.detail;
    if (response.status === 401) showPairing();
    throw new Error(detail || `The request failed (${response.status}).`);
  }
  return response;
}

async function json(path, options) {
  return (await api(path, options)).json();
}

function post(body, method = "POST") {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function message(text, isError = false, id = "notice") {
  const node = byId(id);
  node.hidden = !text;
  node.textContent = text;
  node.classList.toggle("error", isError);
}

async function run(action, control, errorId = "notice") {
  if (control) control.disabled = true;
  message("", false, errorId);
  try {
    await action();
  } catch (error) {
    message(error.message, true, errorId);
  } finally {
    if (control) control.disabled = false;
  }
}

function showPairing() {
  byId("workspace").hidden = true;
  byId("pairing").hidden = false;
  for (const dialog of selectAll("dialog[open]")) dialog.close();
}

async function connect() {
  const info = await json("status");
  if (state.code) sessionStorage.setItem("autodialer-code", state.code);
  value("provider", info.provider);
  value("engine", info.engine === "fixture transcript" ? "Fixture transcripts" : info.engine);
  state.androidUrl = info.android_url;
  byId("android-open").hidden = !state.androidUrl;
  byId("pairing").hidden = true;
  byId("workspace").hidden = false;
  await refreshJobs();
}

function jobState(job) {
  if (job.running) return job.paused ? "Pausing" : "Processing";
  if (job.queued) return job.paused ? "Paused" : "Queued";
  if (job.review) return "Needs review";
  if (job.failed) return "Finished with failures";
  return "Completed";
}

function renderJobs() {
  const metrics = { total: 0, queued: 0, done: 0, review: 0 };
  for (const job of state.jobs) {
    metrics.total += job.total;
    metrics.queued += job.queued + job.running;
    metrics.done += job.done;
    metrics.review += job.review;
  }
  value("total", metrics.total.toLocaleString());
  value("queue-total", metrics.queued.toLocaleString());
  value("done-total", metrics.done.toLocaleString());
  value("review-total", metrics.review.toLocaleString());
  value("job-count", state.jobs.length);
  const signature = JSON.stringify([state.job, state.jobs]);
  if (signature !== state.listSignature) {
    state.listSignature = signature;
    const nodes = state.jobs.map((job) => {
      const node = button("", async () => {
        setJob(job.id);
        renderJobs();
        await refreshJobs();
      });
      node.className = "job-link";
      if (job.id === state.job) node.setAttribute("aria-current", "true");
      node.append(element("strong", job.name), element("span", `${jobState(job)} · ${job.total} records`));
      return node;
    });
    byId("job-list").replaceChildren(...(nodes.length ? nodes : [element("p", "No jobs yet.", "record")]));
  }
  const selected = state.jobs.find((job) => job.id === state.job);
  byId("job-detail").hidden = !selected;
  byId("empty-detail").hidden = Boolean(selected);
  if (!selected) return null;
  value("job-title", selected.name);
  const synthetic = selected.synthetic ? " · Synthetic data" : "";
  value("job-subtitle", `${jobState(selected)} · Workflow revision ${selected.workflow_id}${synthetic}`);
  const pause = byId("pause");
  pause.hidden = !(selected.queued || selected.running);
  pause.textContent = selected.paused ? "Resume" : "Pause";
  return selected;
}

function setJob(id) {
  state.job = id;
  state.page = 0;
  byId("filter").value = "";
  state.recordsSignature = null;
  byId("records").replaceChildren();
  byId("pagination").hidden = true;
}

function recordNode(record, job) {
  const row = element("article", undefined, "record");
  const heading = element("div", undefined, "record-title");
  heading.append(element("strong", record.destination), element("span", states[record.status], `badge ${record.status}`));
  if (record.label) heading.append(element("strong", record.label));
  if (record.status === "review") heading.append(button("Review", () => openReview(job, record)));
  row.append(heading);
  if (record.transcript) row.append(element("p", record.transcript, "transcript"));
  if (record.reason && record.status !== "done") row.append(element("p", record.reason));
  if (record.reviewed_at) row.append(element("p", record.review_note ? `Reviewed · ${record.review_note}` : "Manually reviewed"));
  return row;
}

async function refreshJobs() {
  const refreshId = ++state.refreshId;
  const jobs = await json("jobs");
  if (refreshId !== state.refreshId) return;
  state.jobs = jobs;
  if (state.job === null && jobs.length) setJob(jobs[0].id);
  const selected = renderJobs();
  if (!selected) return;
  const filter = byId("filter").value;
  const total = filter ? selected[filter] : selected.total;
  const lastPage = Math.max(0, Math.ceil(total / pageSize) - 1);
  state.page = Math.min(lastPage, state.page);
  const query = new URLSearchParams({ limit: pageSize, offset: state.page * pageSize });
  if (filter) query.set("status", filter);
  const items = await json(`jobs/${selected.id}/items?${query}`);
  if (refreshId !== state.refreshId || state.job !== selected.id) return;
  const signature = JSON.stringify([selected.id, filter, state.page, items]);
  if (signature !== state.recordsSignature) {
    state.recordsSignature = signature;
    byId("records").replaceChildren(...(items.length
      ? items.map((item) => recordNode(item, selected))
      : [element("p", "No records match this filter.", "record")]));
  }
  byId("pagination").hidden = lastPage === 0;
  byId("prev").disabled = state.page === 0;
  byId("next").disabled = state.page === lastPage;
  value("page-number", `Page ${state.page + 1} of ${lastPage + 1}`);
}

async function startDemo() {
  const result = await json("jobs/demo", { method: "POST" });
  setJob(result.id);
  await refreshJobs();
  message("Synthetic demo started.");
}

function setRuleNumbers() {
  const cards = selectAll("#rules fieldset");
  cards.forEach((card, index) => {
    card.querySelector(".rule-legend").textContent = `Rule ${index + 1}`;
    card.querySelector(".remove-rule").disabled = cards.length <= 1;
  });
  byId("add-rule").disabled = cards.length >= 20;
}

function addRule(rule = { label: "", phrases: [] }) {
  const card = byId("rule-template").content.firstElementChild.cloneNode(true);
  card.querySelector(".rule-label").value = rule.label;
  card.querySelector(".rule-phrases").value = rule.phrases.join("\n");
  card.querySelector(".remove-rule").addEventListener("click", () => {
    card.remove();
    setRuleNumbers();
  });
  byId("rules").append(card);
  setRuleNumbers();
  return card;
}

function showWorkflow(workflow) {
  const fields = byId("workflow-form").elements;
  fields.namedItem("name").value = workflow.name;
  fields.namedItem("digits").value = workflow.digits;
  byId("rules").replaceChildren();
  for (const rule of workflow.rules) addRule(rule);
  state.revision = workflow.revision;
  value("revision", `Revision ${state.revision}`);
}

async function refreshAudit(older = false) {
  const before = older ? `?before=${state.audit.at(-1).id}` : "";
  const events = await json(`audit${before}`);
  state.audit = older ? [...state.audit, ...events] : events;
  const rows = state.audit.map((event) => {
    const line = element("article", undefined, "record");
    const identifiers = [event.at, event.job_id && `Job ${event.job_id}`, event.item_id && `Record ${event.item_id}`];
    if (event.details.revision) identifiers.push(`Revision ${event.details.revision}`);
    if (event.details.attempts) identifiers.push(`Attempt ${event.details.attempts}`);
    line.append(element("strong", auditLabels[event.event] || event.event), element("p", identifiers.filter(Boolean).join(" · ")));
    return line;
  });
  byId("audit-events").replaceChildren(...(rows.length ? rows : [element("p", "No events recorded.", "record")]));
  byId("audit-pagination").hidden = events.length < 100;
}

async function openReview(job, record) {
  const form = byId("review-form");
  form.reset();
  message("", false, "review-error");
  state.review = record;
  const dialog = byId("review-dialog");
  value("review-context", `${record.destination} · ${record.reason}`);
  value("review-transcript", record.transcript || "No transcript available.");
  byId("review-labels").replaceChildren();
  const audio = byId("review-audio");
  audio.hidden = true;
  dialog.showModal();
  try {
    const workflow = await json(`workflow/${job.workflow_id}`);
    if (state.review !== record) return;
    byId("review-labels").replaceChildren(...workflow.rules.map((rule) => {
      const option = element("option");
      option.value = rule.label;
      return option;
    }));
    if (record.fixture) {
      const blob = await (await api(`audio/${record.fixture}`)).blob();
      if (state.review !== record) return;
      state.audioUrl = URL.createObjectURL(blob);
      audio.src = state.audioUrl;
      audio.hidden = false;
    }
  } catch (error) {
    message(error.message, true, "review-error");
  }
}

function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = element("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has("code")) {
  state.code = fragment.get("code");
  history.replaceState(null, "", location.pathname + location.search);
}
byId("pair-form").addEventListener("submit", (event) => {
  event.preventDefault();
  state.code = event.currentTarget.elements.namedItem("code").value.trim();
  run(connect, event.submitter, "pair-error");
});
for (const nav of selectAll("[data-view]")) {
  nav.addEventListener("click", () => {
    const view = nav.dataset.view;
    state.view = view;
    for (const item of selectAll("[data-view]")) {
      if (item === nav) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
      byId(`${item.dataset.view}-view`).hidden = item.dataset.view !== view;
    }
    run(async () => {
      if (view === "jobs") await refreshJobs();
      if (view === "workflow" && state.revision === null) showWorkflow(await json("workflow"));
      if (view === "audit") await refreshAudit();
    });
  });
}

byId("demo").addEventListener("click", () => run(startDemo, byId("demo")));
byId("empty-demo").addEventListener("click", () => run(startDemo, byId("empty-demo")));
byId("import-open").addEventListener("click", () => {
  byId("import-form").reset();
  message("", false, "import-error");
  byId("import-dialog").showModal();
});
byId("import-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const file = event.currentTarget.elements.namedItem("file").files[0];
  run(async () => {
    const job = await json(`jobs/import?filename=${encodeURIComponent(file.name)}`, { method: "POST", body: file });
    byId("import-dialog").close();
    setJob(job.id);
    await refreshJobs();
    message(`Imported ${job.total} destinations. Resume the job to process them.`);
  }, event.submitter, "import-error");
});
for (const control of selectAll("[data-close]")) {
  control.addEventListener("click", () => control.closest("dialog").close());
}
byId("pause").addEventListener("click", () => run(async () => {
  const job = state.jobs.find((entry) => entry.id === state.job);
  await json(`jobs/${job.id}/${job.paused ? "resume" : "pause"}`, { method: "POST" });
  await refreshJobs();
}, byId("pause")));
byId("filter").addEventListener("change", () => {
  state.page = 0;
  run(refreshJobs);
});
for (const [id, direction] of [["prev", -1], ["next", 1]]) {
  byId(id).addEventListener("click", () => {
    state.page += direction;
    run(refreshJobs);
  });
}
byId("export").addEventListener("click", () => run(async () => {
  const format = byId("format").value;
  const job = state.job;
  const result = await api(`jobs/${job}/export/${format}`);
  download(await result.blob(), `autodialer-${job}.${format}`);
}, byId("export")));
byId("add-rule").addEventListener("click", () => addRule().querySelector("input").focus());
byId("workflow-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  run(async () => {
    const rules = selectAll("#rules fieldset").map((card) => ({
      label: card.querySelector(".rule-label").value.trim(),
      phrases: card.querySelector(".rule-phrases").value.split("\n").map((phrase) => phrase.trim()).filter(Boolean),
    }));
    const workflow = { name: form.elements.namedItem("name").value, digits: form.elements.namedItem("digits").value, rules };
    showWorkflow(await json("workflow", post(workflow, "PUT")));
    message("Workflow saved for future imports.");
  }, event.submitter);
});
byId("review-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const record = state.review;
  const inputs = new FormData(event.currentTarget);
  run(async () => {
    await json(`jobs/${record.job_id}/items/${record.id}/review`, post({ label: inputs.get("label"), note: inputs.get("note") }));
    byId("review-dialog").close();
    await refreshJobs();
    message("Review saved.");
  }, event.submitter, "review-error");
});
byId("review-dialog").addEventListener("close", () => {
  state.review = null;
  if (state.audioUrl) {
    const audio = byId("review-audio");
    audio.pause();
    audio.removeAttribute("src");
    URL.revokeObjectURL(state.audioUrl);
    state.audioUrl = null;
  }
});
byId("android-open").addEventListener("click", () => {
  byId("android-link").value = state.androidUrl;
  byId("android-dialog").showModal();
});
byId("android-link").addEventListener("focus", (event) => event.target.select());
byId("audit-more").addEventListener("click", () => run(() => refreshAudit(true), byId("audit-more")));

connect().catch((error) => {
  showPairing();
  message(error.message, true, "pair-error");
});
let polling = false;
setInterval(async () => {
  if (polling || document.hidden || byId("workspace").hidden || state.view !== "jobs") return;
  polling = true;
  try {
    await refreshJobs();
  } catch (error) {
    if (!byId("workspace").hidden) message(error.message, true);
  } finally {
    polling = false;
  }
}, 1800);
