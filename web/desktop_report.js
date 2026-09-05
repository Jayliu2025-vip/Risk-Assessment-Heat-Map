"use strict";
(() => {
  let api, bootstrap, workspace = null, catalogReports = [], catalogRootToken = null;
  let currentView = "catalog", selectedCatalogIds = [];
  let selectedReport = null, analysisWorkbook = null, batchWorkbook = null;
  let taskId = null, findings = [], selectedIds = [], selectedFindingId = null, riskCatalog = [];
  let pollTimer, pollGeneration = 0, startBusy = false, previewGeneration = 0;
  let period = "", commitToken = null, controlsLoaded = false, controlsWorkbookToken = null;
  let controlsByFinding = {}, ownerDeptByFinding = {}, remediationByFinding = {}, previewBusy = false;
  const $ = id => document.getElementById(id);
  const dims = ["imp_financial","imp_compliance","imp_operation","imp_reputation","imp_fraud","imp_strategy","imp_data","imp_hse"];
  const approved = ["title","fact_summary","source_page","source_excerpt","matched_risk_id","domain","likelihood",...dims,"rationale","needs_review","review_status"];
  const terminal = new Set(["待复核","已完成","失败"]);
  const esc = value => String(value ?? "").replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));

  function message(text, error = false) {
    const node = $("report-status");
    node.textContent = text;
    node.className = "report-status" + (error ? " report-error" : "");
  }

  function safeError(error) {
    const code = error?.code || "";
    if (code === "WORKSPACE_NOT_CONFIGURED") return "请先设置单主体信息目录。";
    if (code === "WORKSPACE_ENTITY_MISMATCH") return "该目录已属于另一主体，不能直接改换主体。";
    if (code === "REPORT_REVIEW_INCOMPLETE") return "请先接受或排除全部发现。";
    if (code === "SOURCE_RESELECT_REQUIRED" || code === "SOURCE_HASH_CHANGED") return "原始报告不可用或已变更，请重新选择报告。";
    if (code.startsWith("WORKBOOK_")) return "正式工作簿不可用、已变更或与当前批次不匹配。";
    if (code.startsWith("MODEL_")) return "模型配置尚未验证或连接不可用，请保存并重新测试。";
    if (code === "PREVIEW_REQUIRED") return "提交预览已失效，请重新生成。";
    return error?.message || "操作未完成，请检查输入后重试。";
  }

  async function call(name, ...args) {
    try {
      if (!api || typeof api[name] !== "function") throw {code:"API_UNAVAILABLE"};
      const value = await api[name](...args);
      if (value && value.ok === false) throw value;
      return value?.ok === true ? Object.fromEntries(Object.entries(value).filter(([key]) => key !== "ok")) : value;
    } catch (error) {
      message(safeError(error), true);
      throw error;
    }
  }

  function showView(name) {
    currentView = name;
    document.querySelectorAll(".desktop-view").forEach(view => view.classList.toggle("active", view.id === `desktop-view-${name}`));
    document.querySelectorAll(".desktop-nav").forEach(button => button.classList.toggle("active", button.dataset.desktopView === name));
    renderCatalogSelection();
    window.scrollTo(0, 0);
  }

  function moveDashboard() {
    const main = document.querySelector("body > main");
    const bar = document.querySelector("body > header .bar");
    if (main) $("desktop-dashboard-host").append(main);
    if (bar) $("desktop-dashboard-toolbar").append(bar);
  }

  function renderWorkspace() {
    $("catalog-root-path").textContent = bootstrap?.catalog_root || "尚未设置";
    $("catalog-workspace-setup").hidden = Boolean(workspace);
    $("catalog-ready").hidden = !workspace;
    $("catalog-add-report").disabled = !workspace;
    $("catalog-entity-label").textContent = workspace ? `当前主体：${workspace.entity_name}` : "尚未设置被审计主体";
    renderCatalog();
  }

  function catalogFilters() {
    const projects = [...new Set(catalogReports.map(report => report.audit_project))].sort();
    const dates = [...new Set(catalogReports.map(report => report.upload_date))].sort().reverse();
    const project = $("catalog-project-filter"), date = $("catalog-date-filter");
    const projectValue = project.value, dateValue = date.value;
    project.innerHTML = '<option value="">全部项目</option>' + projects.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
    date.innerHTML = '<option value="">全部日期</option>' + dates.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
    project.value = projects.includes(projectValue) ? projectValue : "";
    date.value = dates.includes(dateValue) ? dateValue : "";
  }

  function filteredReports() {
    const query = $("catalog-search").value.trim().toLowerCase();
    const project = $("catalog-project-filter").value, date = $("catalog-date-filter").value;
    return catalogReports.filter(report => (!query || report.report_title.toLowerCase().includes(query)) &&
      (!project || report.audit_project === project) && (!date || report.upload_date === date));
  }

  function renderCatalog() {
    if (!workspace) return;
    catalogFilters();
    const reports = filteredReports();
    $("catalog-empty").hidden = catalogReports.length > 0;
    $("catalog-table-wrap").hidden = catalogReports.length === 0;
    $("catalog-clear-reports").hidden = catalogReports.length === 0;
    $("catalog-report-rows").innerHTML = reports.map(report => `<tr class="${selectedCatalogIds.includes(report.report_id) ? "selected" : ""}" data-catalog-report-id="${esc(report.report_id)}"><td><input type="checkbox" data-catalog-check="${esc(report.report_id)}" aria-label="选择 ${esc(report.report_title)}" ${selectedCatalogIds.includes(report.report_id) ? "checked" : ""}></td><td>${esc(report.upload_date)}</td><td>${esc(report.audit_project)}</td><td><span class="catalog-title">${esc(report.report_title)}</span><small>${esc(report.report_id)}</small></td><td>${esc(report.report_date || "—")}</td><td>v${Number(report.recognition_version)}</td><td><span class="catalog-status">${esc(report.status)}</span></td><td>${Number(report.finding_count)} 项</td><td><button class="btn sm" data-catalog-trash="${esc(report.report_id)}" type="button">删除</button></td></tr>`).join("");
    document.querySelectorAll("[data-catalog-check]").forEach(input => input.addEventListener("change", () => {
      const id = input.dataset.catalogCheck;
      selectedCatalogIds = input.checked ? [...new Set([...selectedCatalogIds, id])] : selectedCatalogIds.filter(value => value !== id);
      renderCatalog();
    }));
    document.querySelectorAll("[data-catalog-trash]").forEach(button => button.addEventListener("click", async () => {
      const report = catalogReports.find(item => item.report_id === button.dataset.catalogTrash);
      if (!report || !confirm(`将“${report.report_title}”的结构化信息移入回收站？\n不会删除原始报告、历史批次或生成工作簿。`)) return;
      await call("trash_catalog_report", report.report_id);
      selectedCatalogIds = selectedCatalogIds.filter(value => value !== report.report_id);
      await refreshCatalog();
      message("报告信息已移入回收站。可恢复操作将在后续版本提供。", false);
    }));
    renderCatalogSelection();
  }

  function renderCatalogSelection() {
    const selected = catalogReports.filter(report => selectedCatalogIds.includes(report.report_id));
    const visible = currentView === "catalog" && selected.length > 0;
    $("catalog-selection").hidden = !visible;
    $("catalog-selection-count").textContent = `已选择 ${selected.length} 份报告`;
    $("catalog-selection-tags").innerHTML = selected.map(report => `<span>${esc(report.audit_project)}</span>`).join("");
  }

  async function refreshCatalog() {
    const result = await call("list_catalog_reports");
    catalogReports = result.reports || [];
    selectedCatalogIds = selectedCatalogIds.filter(id => catalogReports.some(report => report.report_id === id));
    renderCatalog();
  }

  function resetAnalysis() {
    selectedReport = null; analysisWorkbook = null; taskId = null; findings = []; selectedIds = []; selectedFindingId = null;
    $("report-file-name").textContent = "尚未选择";
    $("report-workbook-name").textContent = "尚未选择";
    $("report-audit-project").value = ""; $("report-title").value = ""; $("report-date").value = "";
    $("report-finding-form").__findingId = "";
    $("report-step-upload").hidden = false; $("report-step-extract").hidden = true; $("report-step-review").hidden = true;
    $("report-save-catalog-wrap").hidden = true;
    setReportStep("upload");
  }

  function setReportStep(name) {
    ["upload","extract","review","commit"].forEach(value => $("report-tab-" + value).setAttribute("aria-current", value === name ? "step" : "false"));
  }

  function beginAddReport() {
    if (!workspace) { message("请先设置单主体信息目录。", true); return; }
    resetAnalysis();
    showView("review");
  }

  function profileOptions() {
    const profiles = bootstrap?.profiles || [];
    $("report-model-profile").innerHTML = profiles.length ? profiles.map(profile => `<option value="${esc(profile.name)}">${esc(profile.name)} · ${esc(profile.model)}</option>`).join("") : '<option value="">尚未配置模型</option>';
    const domain = document.querySelector('[data-finding-field="domain"]');
    domain.innerHTML = (bootstrap?.domains || []).map(item => `<option value="${esc(item)}">${esc(item)}</option>`).join("");
    profileDetails();
  }

  function profileDetails() {
    const profile = (bootstrap?.profiles || []).find(item => item.name === $("report-model-profile").value);
    $("report-model-summary").textContent = profile ? `模型：${profile.name} / ${profile.model}；目标主机：${new URL(profile.base_url).hostname}` : "请先展开“模型设置”，保存并测试一个模型配置。";
  }

  async function saveProfile() {
    const value = {name:$("model-name").value.trim(), base_url:$("model-base-url").value.trim(), model:$("model-model").value.trim(), api_key:$("model-api-key").value, supports_vision:$("model-supports-vision").checked};
    const saved = await call("save_model_profile", value);
    $("model-api-key").value = "";
    bootstrap.profiles = (bootstrap.profiles || []).filter(profile => profile.name !== saved.profile.name).concat(saved.profile);
    profileOptions(); $("report-model-profile").value = saved.profile.name; profileDetails();
    message("模型设置已保存，请测试连接后再分析。", false);
  }

  async function chooseReport() {
    const item = await call("choose_report", "report");
    selectedReport = item.selection_token; $("report-file-name").textContent = `已选择：${item.basename}`;
    if (!$("report-title").value.trim()) $("report-title").value = item.basename.replace(/\.(pdf|docx)$/i, "");
  }

  async function chooseAnalysisWorkbook() {
    const item = await call("choose_report", "workbook"); analysisWorkbook = item.selection_token; $("report-workbook-name").textContent = `已选择：${item.basename}`;
  }

  async function startAnalysis() {
    if (startBusy) return;
    if (!selectedReport || !analysisWorkbook || !$("report-audit-project").value.trim() || !$("report-title").value.trim() || !$("report-model-profile").value) {
      message("请选择报告、风险目录工作簿和模型，并填写审计项目及报告名称。", true); return;
    }
    startBusy = true; $("report-start").disabled = true; const generation = ++pollGeneration;
    try {
      const result = await call("start_analysis", selectedReport, analysisWorkbook, "CATALOG", $("report-model-profile").value);
      taskId = result.task.task_id; riskCatalog = result.risk_catalog || [];
      $("report-step-upload").hidden = true; $("report-step-extract").hidden = false; setReportStep("extract");
      await pollTask(taskId, generation);
    } finally {
      if (generation === pollGeneration) { startBusy = false; $("report-start").disabled = false; }
    }
  }

  async function pollTask(localTaskId, generation) {
    const result = await call("get_task", localTaskId);
    if (generation !== pollGeneration) return;
    const task = result.task; $("report-extraction-method").textContent = `状态：${task.status}；提取方式：${task.extraction_method || "本地处理"}`;
    if (!terminal.has(task.status)) { pollTimer = setTimeout(() => pollTask(localTaskId, generation).catch(() => {}), 750); return; }
    if (task.status === "失败") { message("报告处理失败，可重新选择后重试。", true); return; }
    findings = (await call("get_findings", localTaskId)).findings || [];
    $("report-step-extract").hidden = true; $("report-step-review").hidden = false; setReportStep("review");
    renderFindings(); updateCatalogSaveState();
    message(`已识别 ${findings.length} 项发现。模型输出仅供审计判断参考。`, false);
  }

  function value(finding, key) {
    if (key === "needs_review") return finding.needs_review ? "true" : "false";
    if (dims.includes(key)) return finding.impact_scores?.[key] ?? "";
    return finding[key] ?? "";
  }

  function formValue() {
    const payload = {impact_scores:{}};
    approved.forEach(key => {
      const input = document.querySelector(`[data-finding-field="${key}"]`);
      let fieldValue = input?.type === "checkbox" ? input.checked : input?.value;
      if (dims.includes(key)) { payload.impact_scores[key] = fieldValue === "" ? null : Number(fieldValue); return; }
      if (key === "likelihood") fieldValue = fieldValue === "" ? null : Number(fieldValue);
      if (key === "needs_review") fieldValue = Boolean(fieldValue);
      payload[key] = fieldValue;
    });
    return payload;
  }

  function fillForm(finding) {
    approved.forEach(key => {
      const input = document.querySelector(`[data-finding-field="${key}"]`);
      if (!input) return;
      if (input.type === "checkbox") input.checked = Boolean(finding[key]); else input.value = value(finding, key);
    });
    $("report-finding-form").__findingId = finding.finding_id;
  }

  function renderFindings() {
    $("report-findings").innerHTML = findings.map(finding => `<button type="button" class="report-finding" data-finding-id="${esc(finding.finding_id)}" aria-selected="${selectedIds.includes(finding.finding_id)}"><strong>${esc(finding.finding_id)} · ${esc(finding.title)}</strong><span class="note">${finding.merged_into ? `已关联至 ${esc(finding.merged_into)}` : esc(finding.review_status)}</span></button>`).join("");
    document.querySelectorAll("[data-finding-id]").forEach(button => button.addEventListener("click", event => selectFinding(button.dataset.findingId, event.ctrlKey || event.metaKey)));
    if (findings.length && !$("report-finding-form").__findingId) selectFinding(findings[0].finding_id, false);
  }

  async function selectFinding(id, multiple) {
    if (multiple) { selectedIds = selectedIds.includes(id) ? selectedIds.filter(value => value !== id) : [...selectedIds, id]; renderFindings(); return; }
    selectedIds = [id]; selectedFindingId = id; const generation = ++previewGeneration;
    const finding = findings.find(item => item.finding_id === id); if (!finding) return;
    fillForm(finding); renderFindings();
    try {
      const preview = await call("get_source_preview", taskId, id, selectedReport || undefined);
      if (generation !== previewGeneration || selectedFindingId !== id) return;
      const viewer = $("report-source-viewer"); viewer.replaceChildren();
      if (preview.kind === "pdf" && preview.image_data_url) { const image = document.createElement("img"); image.src = preview.image_data_url; image.alt = `来源页 ${preview.source_page || ""}`; viewer.append(image); }
      else viewer.textContent = [preview.source_report_title, preview.source_audit_project, preview.source_upload_date && `上传 ${preview.source_upload_date}`, preview.source_page, preview.source_excerpt].filter(Boolean).join("\n");
    } catch (_) { if (generation === previewGeneration) $("report-source-viewer").textContent = "来源预览不可用，请核对保存的关键摘录。"; }
  }

  function patchFindings(result) {
    const values = result?.findings || (result?.finding ? [result.finding] : []);
    values.forEach(value => { const index = findings.findIndex(item => item.finding_id === value.finding_id); if (index >= 0) findings[index] = value; else findings.push(value); });
  }

  function updateCatalogSaveState() {
    const complete = findings.length > 0 && findings.every(finding => finding.review_status !== "待确认");
    $("report-save-catalog-wrap").hidden = !complete;
    $("report-tab-commit").setAttribute("aria-current", complete ? "step" : "false");
  }

  async function saveFinding(status, advance = false) {
    const id = $("report-finding-form").__findingId; if (!id) return;
    const payload = formValue(); payload.review_status = status || payload.review_status;
    const result = await call("save_finding", taskId, id, payload); patchFindings(result); renderFindings(); updateCatalogSaveState();
    $("report-review-state").textContent = payload.review_status === "已接受" ? "已接受" : payload.review_status;
    if (advance) { const next = findings.find(item => item.review_status === "待确认" && !item.merged_into); if (next) selectFinding(next.finding_id, false); }
  }

  async function mergeSelected() {
    if (selectedIds.length < 2) { message("请按住 Ctrl 选择至少两项发现。", true); return; }
    const result = await call("merge_findings", taskId, selectedIds, formValue()); patchFindings(result); selectedIds = [selectedIds[0]]; renderFindings(); updateCatalogSaveState();
  }

  async function splitCurrent() {
    const id = $("report-finding-form").__findingId; if (!id) return;
    const base = formValue(); const result = await call("split_finding", taskId, id, [{...base,finding_id:`${id}-A`},{...base,finding_id:`${id}-B`,title:`${base.title}（拆分）`}]); patchFindings(result); renderFindings(); updateCatalogSaveState();
  }

  async function saveToCatalog() {
    const result = await call("save_report_to_catalog", taskId, {audit_project:$("report-audit-project").value.trim(), report_title:$("report-title").value.trim(), report_date:$("report-date").value});
    catalogReports = catalogReports.filter(report => report.report_id !== result.report.report_id).concat(result.report);
    message("结构化报告信息已保存；原始报告和临时提取材料未进入目录。", false); showView("catalog"); renderCatalog();
  }

  function openBatch() {
    const selected = catalogReports.filter(report => selectedCatalogIds.includes(report.report_id));
    if (!selected.length) return;
    $("batch-report-tags").innerHTML = selected.map(report => `<span>${esc(report.upload_date)}｜${esc(report.audit_project)}｜v${Number(report.recognition_version)}</span>`).join("");
    batchWorkbook = null; $("batch-workbook-name").textContent = "尚未选择"; $("report-period").value = "";
    $("batch-setup").hidden = false; $("batch-similar").hidden = true; $("report-step-commit").hidden = true; showView("batch");
  }

  async function chooseBatchWorkbook() {
    const item = await call("choose_report", "workbook"); batchWorkbook = item.selection_token; $("batch-workbook-name").textContent = `已选择：${item.basename}`;
  }

  function primaryFindings() { return findings.filter(finding => !finding.merged_into); }
  function similarityGroups() {
    const groups = new Map();
    primaryFindings().filter(finding => finding.review_status !== "已排除").forEach(finding => {
      const key = finding.matched_risk_id || `NEW-${finding.finding_id}`;
      if (!groups.has(key)) groups.set(key, []); groups.get(key).push(finding);
    });
    return [...groups.entries()].map(([key, items]) => ({key, items}));
  }

  function renderSimilarFindings() {
    $("batch-similar-findings").innerHTML = similarityGroups().map(group => {
      const title = group.items[0].matched_risk_id ? `${group.items[0].matched_risk_id} ${group.items[0].title}` : group.items[0].title;
      const evidence = group.items.map(item => `<div class="batch-evidence"><strong>${esc(item.title)}</strong><small>${esc(item.source_page)}</small></div>`).join("");
      const needsMapping = group.items.some(item => item.review_status === "待确认" || !item.matched_risk_id);
      const mapping = needsMapping ? `<label class="batch-risk-map">匹配当前风险<select data-batch-risk-group="${esc(group.key)}" aria-label="匹配当前风险 ${esc(group.items[0].finding_id)}"><option value="">作为新风险</option>${riskCatalog.map(risk => `<option value="${esc(risk.risk_id)}">${esc(risk.risk_id)} ${esc(risk.name)}</option>`).join("")}</select></label>` : "";
      if (group.items.length > 1) return `<article class="batch-similar-card" data-similar-group="${esc(group.key)}"><div class="batch-similar-head"><span>${esc(title)}</span><span>${group.items.length} 条相关发现</span></div><div class="batch-similar-body"><p class="batch-question">这 ${group.items.length} 条发现可能指向同一项风险</p><p class="batch-help">请判断它们在本次评估中的关系。报告、页码和事实依据都会单独保留。</p>${mapping}${evidence}<div class="batch-choices"><label><input type="radio" name="relation-${esc(group.key)}" value="same" checked> 为同一风险的两条证据</label><label><input type="radio" name="relation-${esc(group.key)}" value="separate"> 分别作为两项风险</label><label><input type="radio" name="relation-${esc(group.key)}" value="skip"> 本次暂不处理</label></div><p class="batch-help">选择第一项后只形成一条风险；不会删除原始发现，也不会平均建议评分。</p></div></article>`;
      return `<article class="batch-similar-card" data-similar-group="${esc(group.key)}"><div class="batch-similar-head"><span>${esc(title)}</span><span>1 条相关发现</span></div><div class="batch-similar-body">${mapping}${evidence}<div class="batch-choices"><label><input type="radio" name="relation-${esc(group.key)}" value="same" checked> 作为现有风险的一条证据</label><label><input type="radio" name="relation-${esc(group.key)}" value="skip"> 本次暂不处理</label></div></div></article>`;
    }).join("");
  }

  async function loadBatchReports() {
    period = $("report-period").value.trim();
    if (!batchWorkbook || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$/.test(period)) { message("请选择当前正式工作簿并填写目标评估期间。", true); return; }
    const result = await call("create_catalog_batch", selectedCatalogIds, batchWorkbook, period);
    taskId = result.task.task_id; findings = result.findings || []; riskCatalog = result.risk_catalog || [];
    selectedReport = null; ownerDeptByFinding = {}; remediationByFinding = {}; resetCommitState();
    $("batch-similar").hidden = false; renderSimilarFindings(); message("请确认相似发现关系，再进入当前风险与控制确认。", false);
  }

  async function confirmRelations() {
    for (const group of similarityGroups()) {
      const selected = document.querySelector(`[name="relation-${CSS.escape(group.key)}"]:checked`)?.value || "same";
      if (selected === "skip") {
        for (const finding of group.items) {
          const saved = await call("save_finding", taskId, finding.finding_id, {...finding,review_status:"已排除"});
          patchFindings(saved);
        }
      } else {
        const mapping = document.querySelector(`[data-batch-risk-group="${CSS.escape(group.key)}"]`);
        if (mapping) {
          for (const finding of group.items) {
            const saved = await call("save_finding", taskId, finding.finding_id, {...finding,matched_risk_id:mapping.value,review_status:"已接受"}); patchFindings(saved);
          }
        }
        if (selected === "same" && group.items.length > 1) {
          const current = findings.filter(item => group.items.some(original => original.finding_id === item.finding_id));
          const result = await call("merge_findings", taskId, current.map(item => item.finding_id), {...current[0],review_status:"已接受"}); patchFindings(result);
        }
      }
    }
    $("batch-similar").hidden = true; $("report-step-commit").hidden = false; renderRiskDecisions();
    message("请确认当前责任部门、整改状态和控制措施。", false);
  }

  function resetCommitState() {
    commitToken = null; controlsLoaded = false; controlsWorkbookToken = null; controlsByFinding = {};
    $("report-controls-confirmed").checked = false; $("report-change-preview").hidden = true; renderCurrentControls();
    $("report-preview").textContent = "载入控制点";
  }

  function defaultOwner(finding) {
    if (!finding.matched_risk_id) return "";
    const matches = riskCatalog.filter(risk => risk.risk_id === finding.matched_risk_id);
    return (matches.find(risk => risk.period === period) || matches[matches.length - 1] || {}).owner_dept || "";
  }

  function ensureDecisionDefaults(finding) {
    if (ownerDeptByFinding[finding.finding_id] === undefined) ownerDeptByFinding[finding.finding_id] = defaultOwner(finding);
    if (remediationByFinding[finding.finding_id] === undefined) remediationByFinding[finding.finding_id] = "未确认";
  }

  function decisionKey(finding) { return [finding.finding_id, ...(finding.merged_finding_ids || [])].join("|"); }
  function invalidateDecision() { commitToken = null; $("report-change-preview").hidden = true; $("report-controls-confirmed").checked = false; }

  function renderRiskDecisions() {
    const container = $("report-risk-decisions"); container.replaceChildren();
    primaryFindings().filter(finding => finding.review_status !== "已排除").forEach(finding => {
      ensureDecisionDefaults(finding);
      const group = document.createElement("section"); group.className = "decision-card";
      const title = document.createElement("h4"); title.textContent = `${finding.matched_risk_id || "新风险"} · ${finding.title}`;
      const evidence = document.createElement("p"); evidence.className = "note"; evidence.textContent = `证据：${decisionKey(finding)}；建议评分不会自动成为正式评分。`;
      const ownerLabel = document.createElement("label"), owner = document.createElement("input"); ownerLabel.textContent = "责任部门"; owner.type = "text"; owner.value = ownerDeptByFinding[finding.finding_id]; owner.setAttribute("aria-label", `责任部门 ${finding.finding_id}`); owner.addEventListener("input", () => { ownerDeptByFinding[finding.finding_id] = owner.value; invalidateDecision(); }); ownerLabel.append(owner);
      const statusLabel = document.createElement("label"), status = document.createElement("select"); statusLabel.textContent = "整改状态"; status.setAttribute("aria-label", `整改状态 ${finding.finding_id}`); ["未确认","未整改","整改中","已整改","不适用"].forEach(value => { const option = document.createElement("option"); option.value = value; option.textContent = value; option.selected = remediationByFinding[finding.finding_id] === value; status.append(option); }); status.addEventListener("change", () => { remediationByFinding[finding.finding_id] = status.value; invalidateDecision(); }); statusLabel.append(status);
      group.append(title, evidence, ownerLabel, statusLabel); container.append(group);
    });
  }

  function decisions(includeControls = false) {
    if (primaryFindings().some(finding => finding.review_status === "待确认")) throw new Error("PENDING_REVIEW");
    return primaryFindings().map(finding => {
      const finding_ids = [finding.finding_id, ...(finding.merged_finding_ids || [])];
      if (finding.review_status === "已排除") return {action:"exclude",finding_ids};
      ensureDecisionDefaults(finding);
      if (!ownerDeptByFinding[finding.finding_id].trim() || remediationByFinding[finding.finding_id] === "未确认") throw new Error("CURRENT_STATE_REQUIRED");
      const result = {action:finding.matched_risk_id ? "merge" : "create",finding_ids,risk_id:finding.matched_risk_id || "",name:finding.title,domain:finding.domain,description:finding.fact_summary,owner_dept:ownerDeptByFinding[finding.finding_id].trim(),period,likelihood:finding.likelihood,impact_scores:finding.impact_scores,rationale:finding.rationale,remediation_status:remediationByFinding[finding.finding_id]};
      if (includeControls) result.controls = (controlsByFinding[finding_ids.join("|")] || []).map(control => ({description:control.description,score:Number(control.score),key:Boolean(control.key)}));
      return result;
    });
  }

  function controlIdentities() { return decisions(false).filter(item => item.action !== "exclude").map(({finding_ids,action,risk_id,period:decisionPeriod}) => ({finding_ids,action,risk_id,period:decisionPeriod})); }
  function editControls(id, controls) { controlsByFinding[id] = controls; $("report-controls-confirmed").checked = false; renderCurrentControls(); }

  function renderCurrentControls() {
    const container = $("report-current-controls"); container.replaceChildren(); if (!controlsLoaded) return;
    Object.entries(controlsByFinding).forEach(([id, controls]) => {
      const group = document.createElement("section"); group.className = "decision-card"; const title = document.createElement("h4"); title.textContent = `风险 ${id} 的当前控制点`; group.append(title);
      controls.forEach((control, index) => {
        const row = document.createElement("div"); row.className = "desktop-actions";
        const description = document.createElement("input"); description.type = "text"; description.value = control.description; description.setAttribute("aria-label", `控制点 ${id}`); description.addEventListener("change", () => { const next = [...controls]; next[index] = {...next[index],description:description.value}; editControls(id, next); });
        const score = document.createElement("select"); score.setAttribute("aria-label", `控制有效性 ${id}`); [1,2,3,4,5].forEach(value => { const option = document.createElement("option"); option.value = String(value); option.textContent = String(value); option.selected = Number(control.score) === value; score.append(option); }); score.addEventListener("change", () => { const next = [...controls]; next[index] = {...next[index],score:Number(score.value)}; editControls(id, next); });
        const key = document.createElement("input"); key.type = "checkbox"; key.checked = Boolean(control.key); key.setAttribute("aria-label", `关键控制 ${id}`); key.addEventListener("change", () => { const next = [...controls]; next[index] = {...next[index],key:key.checked}; editControls(id, next); });
        row.append(description, score, key); group.append(row);
      }); container.append(group);
    });
  }

  function applyLoadedControls(groups, token) {
    controlsByFinding = {}; (groups || []).forEach(group => { controlsByFinding[group.finding_ids.join("|")] = (group.controls || []).map(control => ({description:control.description,score:control.score,key:Boolean(control.key)})); });
    controlsLoaded = true; controlsWorkbookToken = token; renderCurrentControls(); $("report-preview").textContent = "生成变更预览";
  }

  function renderPreview(preview) {
    const labels = {new_risks:"新增风险",updated_risks:"更新风险",new_controls:"新增控制",excluded_count:"排除发现",warnings:"提示"};
    $("report-preview-list").innerHTML = Object.keys(labels).map(key => `<li>${labels[key]}：${esc(JSON.stringify(preview[key] ?? []))}</li>`).join(""); $("report-change-preview").hidden = false;
  }

  async function preview() {
    if (previewBusy) return;
    let checked; try { checked = decisions(false); } catch (_) { message("请先确认责任部门与整改状态。", true); return; }
    previewBusy = true; const button = $("report-preview"); button.disabled = true;
    try {
      if (!controlsLoaded || controlsWorkbookToken !== batchWorkbook) {
        const loaded = await call("preview_commit", taskId, batchWorkbook, period, controlIdentities(), "load_controls"); applyLoadedControls(loaded.controls_by_decision, batchWorkbook); message("已载入当前控制点，请编辑并确认。", false); return;
      }
      if (!$("report-controls-confirmed").checked) { message("请确认当前控制措施。", true); return; }
      const result = await call("preview_commit", taskId, batchWorkbook, period, decisions(true), "preview", true); commitToken = result.commit_token; renderPreview(result); message("变更预览已生成。", false);
    } finally { previewBusy = false; button.disabled = false; }
  }

  async function commit() {
    if (!commitToken) return;
    const button = $("report-commit"); button.disabled = true;
    try {
      const result = await call("commit_to_workbook", taskId, batchWorkbook, period, decisions(true), commitToken); commitToken = null;
      if (!result.period_data || !window.RAHMDesktop.loadPeriodData(result.period_data.period, result.period_data.risks, result.period_data.controls)) throw new Error("PERIOD_DATA_INVALID");
      $("desktop-dashboard-title").textContent = `风险图谱 · ${result.period_data.period}`; $("desktop-dashboard-nav").disabled = false; showView("dashboard"); message(`已生成：${result.workbook_path}`, false);
    } catch (error) { button.disabled = false; throw error; }
  }

  async function configureWorkspace() {
    if (!catalogRootToken || !$("catalog-entity-name").value.trim()) { message("请选择信息目录并填写被审计主体。", true); return; }
    const result = await call("configure_workspace", catalogRootToken, $("catalog-entity-name").value.trim()); workspace = result.workspace; catalogReports = result.reports || []; bootstrap.catalog_root = result.catalog_root; renderWorkspace(); message("单主体信息目录已启用。", false);
  }

  function bindEvents() {
    document.querySelectorAll("[data-desktop-view]").forEach(button => button.addEventListener("click", () => { if (!button.disabled) showView(button.dataset.desktopView); }));
    $("catalog-change-root").addEventListener("click", () => { $("catalog-workspace-setup").hidden = false; message(workspace ? "选择另一目录不会改写当前主体；请确认新目录主体。" : "请选择信息目录并确认主体。", false); });
    $("catalog-choose-root").addEventListener("click", async () => { const result = await call("choose_catalog_root"); catalogRootToken = result.selection_token; $("catalog-root-selection").textContent = result.display_path; });
    $("catalog-save-workspace").addEventListener("click", () => configureWorkspace().catch(() => {}));
    [$("catalog-add-report"), $("catalog-empty-add")].forEach(button => button.addEventListener("click", beginAddReport));
    $("catalog-search").addEventListener("input", renderCatalog); $("catalog-project-filter").addEventListener("change", renderCatalog); $("catalog-date-filter").addEventListener("change", renderCatalog);
    $("catalog-clear-filter").addEventListener("click", () => { $("catalog-search").value = ""; $("catalog-project-filter").value = ""; $("catalog-date-filter").value = ""; renderCatalog(); });
    $("catalog-create-batch").addEventListener("click", openBatch);
    $("catalog-clear-reports").addEventListener("click", async () => { if (!confirm(`将 ${catalogReports.length} 份结构化报告信息移入回收站？\n历史批次和生成工作簿将保留。`)) return; await call("clear_catalog_reports"); selectedCatalogIds = []; await refreshCatalog(); });
    $("catalog-trash").addEventListener("click", () => message("普通删除会进入当前信息目录的回收站；恢复界面将在后续版本提供。", false));
    $("report-choose").addEventListener("click", () => chooseReport().catch(() => {})); $("report-choose-workbook").addEventListener("click", () => chooseAnalysisWorkbook().catch(() => {}));
    $("report-start").addEventListener("click", () => startAnalysis().catch(() => {})); $("report-reselect").addEventListener("click", resetAnalysis);
    $("model-save").addEventListener("click", () => saveProfile().catch(() => {})); $("model-test").addEventListener("click", async () => { const result = await call("test_model_profile", $("report-model-profile").value); message(`模型连接已验证：${result.hostname}`, false); }); $("report-model-profile").addEventListener("change", profileDetails);
    $("report-save").addEventListener("click", () => saveFinding(null, false).catch(() => {})); $("report-accept").addEventListener("click", () => saveFinding("已接受", true).catch(() => {})); $("report-exclude").addEventListener("click", () => saveFinding("已排除", true).catch(() => {}));
    $("report-merge").addEventListener("click", () => mergeSelected().catch(() => {})); $("report-split").addEventListener("click", () => splitCurrent().catch(() => {})); $("report-save-catalog").addEventListener("click", () => saveToCatalog().catch(() => {}));
    $("batch-choose-workbook").addEventListener("click", () => chooseBatchWorkbook().catch(() => {})); $("batch-load-reports").addEventListener("click", () => loadBatchReports().catch(() => {})); $("batch-confirm-relations").addEventListener("click", () => confirmRelations().catch(() => {}));
    $("report-preview").addEventListener("click", () => preview().catch(() => {})); $("report-commit").addEventListener("click", () => commit().catch(() => {}));
  }

  async function init() {
    api = window.pywebview && window.pywebview.api; if (!api) return;
    document.body.classList.add("desktop-mode"); moveDashboard();
    bootstrap = await call("get_bootstrap"); workspace = bootstrap.workspace || null; catalogReports = bootstrap.catalog_reports || [];
    $("desktop-report-shell").hidden = false; $("desktop-report-nav").hidden = true;
    $("desktop-dashboard-nav").disabled = true;
    bindEvents(); profileOptions(); renderWorkspace(); showView("catalog");
  }

  window.addEventListener("pywebviewready", () => init().catch(error => message(safeError(error), true)), {once:true});
})();
