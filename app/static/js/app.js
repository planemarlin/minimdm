/* miniMDM – main JS */

// ── Inline SVG icon helpers ──────────────────────────────────────────────────
const _SVG = {
  edit:         `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4Z"/></svg>`,
  history:      `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>`,
  trash:        `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M10 11v6M14 11v6"/></svg>`,
  external:     `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg>`,
  chevronRight: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>`,
  chevronDown:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>`,
  more:         `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>`,
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function fmtDateOnly(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
}

function escHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function showAlert(container, message, type = "error") {
  const div = document.createElement("div");
  div.className = `alert alert-${type}`;
  div.textContent = message;
  container.prepend(div);
  setTimeout(() => div.remove(), 5000);
}

// Returns true if the field key/name looks like a code or identifier.
function _isIdentifier(key) {
  const k = key.toLowerCase();
  return k === "code" || k.endsWith("_code") || k === "external_id" ||
         k.endsWith("_id") || k.includes("external") || k === "source_id";
}

// ── Reference label resolution ───────────────────────────────────────────────

async function _resolveRefLabels(schema, objConfig) {
  const maps = {};
  const names = {};
  const jobs = [];
  if (objConfig.parent) {
    jobs.push({ key: "_parent", objName: objConfig.parent });
  }
  for (const [k, v] of Object.entries(objConfig.attributes || {})) {
    if (v.reference) jobs.push({ key: k, objName: v.reference });
  }
  await Promise.all(jobs.map(async ({ key, objName }) => {
    try {
      const [recsRes, cfgRes] = await Promise.all([
        fetch(`/api/records/${schema}/${objName}?page_size=500&include_deleted=true`),
        fetch(`/api/schemas/${schema}/objects/${objName}`),
      ]);
      if (!recsRes.ok || !cfgRes.ok) return;
      const recsData = await recsRes.json();
      const refCfg = await cfgRes.json();
      names[key] = refCfg.name || objName;
      const dispKeys = Object.entries(refCfg.attributes || {})
        .filter(([, av]) => !av.reference).slice(0, 2).map(([ak]) => ak);
      const map = {};
      for (const r of recsData.records) {
        map[r._id] = dispKeys.map(dk => r[dk]).filter(Boolean).join(" – ") || r._id;
      }
      maps[key] = map;
    } catch (_) {}
  }));
  return { maps, names };
}

// ── Record list page ─────────────────────────────────────────────────────────

class RecordList {
  constructor({ schema, obj, objConfig }) {
    this.schema = schema;
    this.obj = obj;
    this.objConfig = objConfig;
    this.page = 1;
    this.pageSize = 50;
    this.search = "";
    this.total = 0;
    this.includeDeleted = false;
    this.stateValue = "active";
    this.sourceSystem = "";

    this.tbody = document.getElementById("record-tbody");
    this.paginationEl = document.getElementById("pagination");
    this.totalEl = document.getElementById("total-count");

    const firstNonRef = Object.entries(objConfig.attributes || {}).find(([, v]) => !v.reference);
    this.sortBy = firstNonRef ? firstNonRef[0] : null;
    this.sortDir = "asc";

    const searchInput = document.getElementById("search-input");
    if (searchInput) {
      let timer;
      searchInput.addEventListener("input", (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => { this.search = e.target.value; this.page = 1; this.load(); }, 300);
      });
    }

    const deletedToggle = document.getElementById("show-deleted-toggle");
    if (deletedToggle) {
      deletedToggle.addEventListener("change", (e) => {
        this.includeDeleted = e.target.checked; this.page = 1; this.load();
      });
    }

    const sourceSystemInput = document.getElementById("source-system-filter");
    if (sourceSystemInput) {
      let timer;
      sourceSystemInput.addEventListener("input", (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => { this.sourceSystem = e.target.value.trim(); this.page = 1; this.load(); }, 300);
      });
    }

    this.load();
  }

  // Called by the segmented control buttons in list.html
  setStateFilter(value) {
    this.stateValue = value;
    this.page = 1;
    this.load();
  }

  get userAttributes() {
    return Object.entries(this.objConfig.attributes || {});
  }

  async load() {
    if (!this.tbody) return;
    this.tbody.innerHTML = `<tr><td colspan="20" style="text-align:center;padding:2rem"><span class="spinner"></span></td></tr>`;

    const params = new URLSearchParams({ page: this.page, page_size: this.pageSize });
    if (this.search) params.set("search", this.search);
    if (this.includeDeleted) params.set("include_deleted", "true");
    if (this.stateValue && this.stateValue !== "active") params.set("state", this.stateValue);
    if (this.sourceSystem) params.set("source_system", this.sourceSystem);
    if (this.sortBy) { params.set("sort_by", this.sortBy); params.set("sort_dir", this.sortDir); }

    const res = await fetch(`/api/records/${this.schema}/${this.obj}?${params}`);
    if (!res.ok) {
      const msg = res.status === 403
        ? "You don't have access to this schema. Contact your administrator to request access."
        : "Failed to load records.";
      this.tbody.innerHTML = `<tr><td colspan="20"><div class="alert alert-error">${msg}</div></td></tr>`;
      return;
    }
    const data = await res.json();
    this.total = data.total;
    const { maps: refLabelMaps } = await _resolveRefLabels(this.schema, this.objConfig);
    this.renderRows(data.records, refLabelMaps);
    this._updateSortHeaders();
    this.renderPagination(data.pages);
    if (this.totalEl) this.totalEl.textContent = data.total;
  }

  renderRows(records, refLabelMaps = {}) {
    if (!records.length) {
      this.tbody.innerHTML = `<tr><td colspan="20">
        <div class="empty-state">
          <div class="empty-state__icon">📋</div>
          <div class="empty-state__text">No records found.</div>
        </div></td></tr>`;
      return;
    }

    const attrs = this.userAttributes;
    const schema = this.schema;
    const obj = this.obj;
    const objConfig = this.objConfig;

    this.tbody.innerHTML = records.map((r) => {
      const isDeleted = !!r._deleted_at;
      const recordState = r._state || "active";
      const rowStyle = isDeleted ? "opacity:.5;text-decoration:line-through" : "";
      const cells = [];

      if (objConfig.parent) {
        const pid = r[`_${objConfig.parent}_id`];
        const label = pid ? (refLabelMaps["_parent"]?.[pid] || pid) : "";
        cells.push(`<td style="${rowStyle}">${escHtml(label)}</td>`);
      }

      const remaining = 6 - cells.length;
      for (const [k, v] of attrs.slice(0, remaining)) {
        if (v.reference) {
          const refId = r[`${k}_id`];
          const label = refId ? (refLabelMaps[k]?.[refId] || refId) : "";
          cells.push(`<td style="${rowStyle}">${escHtml(label)}</td>`);
        } else {
          const raw = r[k] ?? "";
          const cellVal = v.type === "date" ? fmtDateOnly(raw) : escHtml(raw);
          const mono = _isIdentifier(k) ? ` class="mdm-mono"` : "";
          cells.push(`<td${mono} style="${rowStyle}">${cellVal}</td>`);
        }
      }

      const statePill = recordState === "draft"
        ? `<span class="mdm-pill mdm-pill-amber" style="margin-left:6px">Draft</span>`
        : recordState === "retired"
          ? `<span class="mdm-pill mdm-pill-slate" style="margin-left:6px">Retired</span>`
          : "";

      const rowActions = isDeleted
        ? `<a class="mdm-rowact" style="opacity:1" href="/${schema}/${obj}/${r._id}/history" title="History">${_SVG.history}</a>
           <span class="mdm-pill mdm-pill-red" style="margin-left:4px">deleted</span>`
        : `<div class="mdm-rowact">
             <a href="/${schema}/${obj}/${r._id}/edit" title="Edit">${_SVG.edit}</a>
             <a href="/${schema}/${obj}/${r._id}/history" title="History">${_SVG.history}</a>
             <button title="Delete" class="danger" onclick="event.stopPropagation();recordList.confirmDelete('${r._id}')">${_SVG.trash}</button>
           </div>${statePill}`;

      const rowClick = isDeleted
        ? `onclick="window.location='/${schema}/${obj}/${r._id}/history'"`
        : `onclick="window.location='/${schema}/${obj}/${r._id}'"`;

      return `<tr style="cursor:pointer" ${rowClick}>
        ${cells.join("")}
        <td class="col-actions" onclick="event.stopPropagation()">${rowActions}</td>
      </tr>`;
    }).join("");
  }

  renderPagination(pages) {
    if (!this.paginationEl) return;
    if (pages <= 1) { this.paginationEl.innerHTML = ""; return; }

    let html = `<button class="page-btn" ${this.page === 1 ? "disabled" : ""}
      onclick="recordList.goPage(${this.page - 1})">&#8592;</button>`;
    for (let p = 1; p <= pages; p++) {
      if (pages > 7 && Math.abs(p - this.page) > 2 && p !== 1 && p !== pages) {
        if (p === 2 || p === pages - 1) html += `<span style="padding:0 .3rem">…</span>`;
        continue;
      }
      html += `<button class="page-btn ${p === this.page ? "page-btn--active" : ""}"
        onclick="recordList.goPage(${p})">${p}</button>`;
    }
    html += `<button class="page-btn" ${this.page === pages ? "disabled" : ""}
      onclick="recordList.goPage(${this.page + 1})">&#8594;</button>`;
    html += `<span class="pagination__info">${this.total} records</span>`;
    this.paginationEl.innerHTML = html;
  }

  setSort(col) {
    if (this.sortBy === col) {
      this.sortDir = this.sortDir === "asc" ? "desc" : "asc";
    } else {
      this.sortBy = col;
      this.sortDir = "asc";
    }
    this.page = 1;
    this.load();
  }

  _updateSortHeaders() {
    document.querySelectorAll(".th-sort-icon").forEach(el => { el.textContent = ""; });
    if (this.sortBy) {
      const icon = document.querySelector(`#th-col-${this.sortBy} .th-sort-icon`);
      if (icon) icon.textContent = this.sortDir === "asc" ? " ↑" : " ↓";
    }
  }

  goPage(p) { this.page = p; this.load(); }

  async confirmDelete(id) {
    if (!confirm("Delete this record? This action can be undone via history.")) return;
    const requireReason = !!this.objConfig.require_change_reason;
    const reason = prompt(`Reason for deletion (${requireReason ? "required" : "optional"}):`) || "";
    if (requireReason && !reason.trim()) {
      alert("A reason is required to delete this record.");
      return;
    }
    const res = await fetch(
      `/api/records/${this.schema}/${this.obj}/${id}?reason=${encodeURIComponent(reason)}`,
      { method: "DELETE" }
    );
    if (res.ok || res.status === 204) {
      this.load();
    } else {
      alert("Failed to delete record.");
    }
  }
}

// ── Record detail page ───────────────────────────────────────────────────────

// Module-level context set by initDetailPage; used by the modal functions.
let _detailCtx = null;

function initDetailPage(schema, obj, recordId, objConfig, opts = {}) {
  _detailCtx = { schema, obj, recordId, requireReason: !!objConfig.require_change_reason };
  loadRecordDetail(schema, obj, recordId, objConfig, opts);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      document.querySelectorAll(".modal-backdrop").forEach(el => { el.style.display = "none"; });
    }
  });
}

async function loadRecordDetail(schema, obj, recordId, objConfig, opts = {}) {
  const container = document.getElementById("detail-container");
  if (!container) return;

  const res = await fetch(`/api/records/${schema}/${obj}/${recordId}?include_deleted=true`);
  if (!res.ok) {
    container.innerHTML = `<div class="alert alert-error">Record not found.</div>`;
    return;
  }
  const record = await res.json();
  const recordState = record._state || "active";

  // Update breadcrumb and page title with first attribute value
  const firstAttrKey = Object.keys(objConfig.attributes || {})[0];
  const recordLabel = firstAttrKey ? (record[firstAttrKey] || recordId) : recordId;
  const crumb = document.getElementById("crumb-record");
  if (crumb) crumb.textContent = recordLabel;
  const pageTitle = document.getElementById("detail-page-title");
  if (pageTitle) pageTitle.textContent = recordLabel;

  // Show code in sub-line if available
  const codeKey = Object.keys(objConfig.attributes || {}).find(k => _isIdentifier(k) && k !== firstAttrKey);
  if (codeKey && record[codeKey]) {
    const sub = document.getElementById("detail-page-sub");
    if (sub) {
      sub.style.display = "";
      sub.innerHTML = `<span>${escHtml(objConfig.name)}</span><span class="dot"></span>
        <span class="mdm-mono" style="font-size:12px;color:var(--mdm-mute)">${escHtml(record[codeKey])}</span>`;
    }
  }

  // Show/hide action buttons
  const publishBtn = document.getElementById("btn-publish");
  const retireBtn  = document.getElementById("btn-retire");
  const editBtn    = document.getElementById("btn-edit");
  const deleteBtn  = document.getElementById("btn-delete");
  if (publishBtn) publishBtn.style.display = (opts.canPublish && recordState === "draft") ? "" : "none";
  if (retireBtn)  retireBtn.style.display  = (opts.canPublish && recordState === "active") ? "" : "none";
  if (editBtn)    editBtn.style.display    = (opts.canWrite && recordState !== "retired") ? "" : "none";
  if (deleteBtn)  deleteBtn.style.display  = (opts.canWrite && recordState !== "retired") ? "" : "none";

  // Parent field
  let parentHtml = "";
  if (objConfig.parent) {
    const parentId = record[`_${objConfig.parent}_id`];
    if (parentId) {
      let parentLabel = parentId;
      let parentDeleted = false;
      try {
        const [prRes, pcRes] = await Promise.all([
          fetch(`/api/records/${schema}/${objConfig.parent}/${parentId}?include_deleted=true`),
          fetch(`/api/schemas/${schema}/objects/${objConfig.parent}`),
        ]);
        if (prRes.ok && pcRes.ok) {
          const pr = await prRes.json();
          const pc = await pcRes.json();
          const dispKeys = Object.entries(pc.attributes || {})
            .filter(([, v]) => !v.reference).slice(0, 2).map(([k]) => k);
          parentLabel = dispKeys.map(k => pr[k]).filter(Boolean).join(" – ") || parentId;
          parentDeleted = !!pr._deleted_at;
        }
      } catch (_) {}
      const deletedBadge = parentDeleted ? ' <span class="mdm-pill mdm-pill-red">deleted</span>' : "";
      parentHtml = `<div>
        <div class="mdm-attr-label">${escHtml(objConfig.parent)} (parent)</div>
        <div class="mdm-attr-value">
          ${parentDeleted
            ? `${escHtml(parentLabel)}${deletedBadge}`
            : `<a href="/${schema}/${objConfig.parent}/${parentId}">${escHtml(parentLabel)}</a>`}
        </div>
      </div>`;
    }
  }

  // Resolve reference fields
  const attrs = Object.entries(objConfig.attributes || {});
  const refResolved = {};
  await Promise.all(
    attrs.filter(([, v]) => v.reference).map(async ([k, v]) => {
      const refId = record[`${k}_id`];
      if (!refId) return;
      try {
        const [rRes, cfgRes] = await Promise.all([
          fetch(`/api/records/${schema}/${v.reference}/${refId}?include_deleted=true`),
          fetch(`/api/schemas/${schema}/objects/${v.reference}`),
        ]);
        if (!rRes.ok) return;
        const refRec = await rRes.json();
        const refCfg = cfgRes.ok ? await cfgRes.json() : {};
        const dispKeys = Object.entries(refCfg.attributes || {})
          .filter(([, av]) => !av.reference).slice(0, 2).map(([ak]) => ak);
        const label = dispKeys.map(ak => refRec[ak]).filter(Boolean).join(" – ") || refId;
        refResolved[k] = { label, deleted: !!refRec._deleted_at, id: refId, obj: v.reference };
      } catch (_) {}
    })
  );

  // Build attribute cells
  const fields = attrs.map(([k, v]) => {
    if (v.reference) {
      const refId = record[`${k}_id`];
      if (!refId) return `<div>
        <div class="mdm-attr-label">${escHtml(v.name || k)}</div>
        <div class="mdm-attr-value" style="color:var(--mdm-mute-2)">—</div>
      </div>`;
      const ref = refResolved[k];
      const label = ref ? ref.label : refId;
      const valueHtml = ref && ref.deleted
        ? `${escHtml(label)} <span class="mdm-pill mdm-pill-red">deleted</span>`
        : ref
          ? `<a href="/${schema}/${ref.obj}/${refId}">${escHtml(label)}</a>`
          : escHtml(String(refId));
      return `<div>
        <div class="mdm-attr-label">${escHtml(v.name || k)}</div>
        <div class="mdm-attr-value">${valueHtml}</div>
      </div>`;
    }
    const val = record[k];
    const displayVal = val == null ? "—"
      : v.type === "date" ? fmtDateOnly(val)
      : escHtml(String(val));
    const monoCls = _isIdentifier(k) ? " mono" : "";
    return `<div>
      <div class="mdm-attr-label">${escHtml(v.name || k)}</div>
      <div class="mdm-attr-value${monoCls}${val == null ? '" style="color:var(--mdm-mute-2)' : ''}">${displayVal}</div>
    </div>`;
  }).join("");

  // Chip row
  const stateLabel = { active: "Active · Master", draft: "Draft", retired: "Retired" }[recordState] || recordState;
  const pillCls = recordState === "active" ? "mdm-pill-green"
    : recordState === "draft" ? "mdm-pill-amber"
    : "mdm-pill-slate";
  const sourceHtml = record._source_system
    ? `<div style="display:flex;gap:6px;align-items:center">
        <span>Source</span>
        <span style="color:var(--mdm-ink-2)">${escHtml(record._source_system)}</span>
        ${record._source_id ? `<span style="color:var(--mdm-mute-2)">·</span><span class="mdm-mono" style="color:var(--mdm-ink-2)">${escHtml(record._source_id)}</span>` : ""}
      </div>` : "";

  const chipRow = `<div style="margin-top:22px;padding-top:16px;border-top:1px solid var(--mdm-border);display:flex;align-items:center;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--mdm-mute)">
    <span class="mdm-pill ${pillCls}">${stateLabel}</span>
    <div style="display:flex;gap:6px"><span>Created</span><span class="mdm-mono" style="color:var(--mdm-ink-2)">${fmtDate(record._created_at)}</span></div>
    <div style="display:flex;gap:6px"><span>Updated</span><span class="mdm-mono" style="color:var(--mdm-ink-2)">${fmtDate(record._updated_at)}</span></div>
    ${sourceHtml}
  </div>`;

  container.innerHTML = `<div class="mdm-attrs">${parentHtml}${fields}</div>${chipRow}`;

  const relatedContainer = document.getElementById("related-container");
  if (relatedContainer) {
    await _renderChildPanels(relatedContainer, schema, obj, recordId);
  }
}

async function _renderChildPanels(container, schema, parentObj, parentId) {
  let schemaConfig;
  try {
    const res = await fetch(`/api/schemas/${schema}`);
    if (!res.ok) return;
    schemaConfig = await res.json();
  } catch (_) { return; }

  const childObjects = Object.entries(schemaConfig.objects || {})
    .filter(([, cfg]) => cfg.parent === parentObj);

  const refObjects = [];
  for (const [objKey, objCfg] of Object.entries(schemaConfig.objects || {})) {
    for (const [attrKey, attrCfg] of Object.entries(objCfg.attributes || {})) {
      if (attrCfg.reference === parentObj) {
        refObjects.push({ objKey, objCfg, attrKey, attrCfg });
      }
    }
  }

  if (!childObjects.length && !refObjects.length) return;

  const panels = [
    ...childObjects.map(([childKey, childCfg]) => ({
      key: childKey, cfg: childCfg,
      params: new URLSearchParams({ parent_id: parentId, page_size: 500 }),
    })),
    ...refObjects.map(({ objKey, objCfg, attrKey, attrCfg }) => ({
      key: objKey, cfg: objCfg,
      label: `${objCfg.name || objKey} (via ${attrCfg.name || attrKey})`,
      params: new URLSearchParams({ ref_field: attrKey, ref_id: parentId, page_size: 500 }),
    })),
  ];

  for (const { key: childKey, cfg: childCfg, label, params } of panels) {
    const sectionHead = document.createElement("div");
    sectionHead.className = "mdm-section-head";
    sectionHead.innerHTML = `<h3>${escHtml(label || childCfg.name || childKey)}</h3><span class="count">loading…</span>`;
    container.appendChild(sectionHead);

    const tableWrap = document.createElement("div");
    tableWrap.className = "mdm-table-wrap";
    tableWrap.innerHTML = `<div style="padding:.75rem 1rem;font-size:.85rem;color:var(--mdm-mute)"><span class="spinner"></span></div>`;
    container.appendChild(tableWrap);

    try {
      const [recsRes, cfgRes] = await Promise.all([
        fetch(`/api/records/${schema}/${childKey}?` + params),
        fetch(`/api/schemas/${schema}/objects/${childKey}`),
      ]);
      if (!recsRes.ok) {
        tableWrap.innerHTML = `<div class="alert alert-error" style="margin:.75rem">Failed to load records.</div>`;
        continue;
      }
      const data = await recsRes.json();
      const refCfg = cfgRes.ok ? await cfgRes.json() : {};

      sectionHead.querySelector(".count").textContent =
        `${data.total} record${data.total !== 1 ? "s" : ""} · linked to this ${parentObj}`;

      if (!data.total) {
        tableWrap.innerHTML = `<div style="padding:.75rem 1rem;font-size:.85rem;color:var(--mdm-mute)">No records.</div>`;
        continue;
      }

      const cols = Object.entries(refCfg.attributes || {}).filter(([, v]) => !v.reference).slice(0, 4);
      const thead = `<thead><tr>${cols.map(([k, v]) => `<th>${escHtml((v.name || k).toUpperCase())}</th>`).join("")}<th class="col-actions"></th></tr></thead>`;
      const tbody = data.records.map(r => {
        const cells = cols.map(([k, v]) => {
          const mono = _isIdentifier(k) ? ` class="mdm-mono"` : "";
          return `<td${mono}>${escHtml(String(r[k] ?? ""))}</td>`;
        }).join("");
        const rowAct = `<div class="mdm-rowact"><a href="/${schema}/${childKey}/${r._id}" title="Open">${_SVG.external}</a></div>`;
        return `<tr style="cursor:pointer" onclick="window.location.href='/${schema}/${childKey}/${r._id}'">${cells}<td class="col-actions" onclick="event.stopPropagation()">${rowAct}</td></tr>`;
      }).join("");

      tableWrap.innerHTML = `<table class="mdm-table">${thead}<tbody>${tbody}</tbody></table>`;
    } catch (_) {
      tableWrap.innerHTML = `<div class="alert alert-error" style="margin:.75rem">Failed to load records.</div>`;
    }
  }
}

// ── Detail page modal functions (called by onclick= in detail.html) ──────────

function openDeleteModal() {
  document.getElementById("delete-reason").value = "";
  document.getElementById("delete-modal-backdrop").style.display = "flex";
  document.getElementById("delete-reason").focus();
}
function closeDeleteModal(event) {
  if (event && event.target !== document.getElementById("delete-modal-backdrop")) return;
  document.getElementById("delete-modal-backdrop").style.display = "none";
}
async function submitDelete() {
  const { schema, obj, recordId, requireReason } = _detailCtx;
  const reason = document.getElementById("delete-reason").value.trim();
  if (requireReason && !reason) { alert("A reason is required to delete this record."); return; }
  const url = `/api/records/${schema}/${obj}/${recordId}` + (reason ? `?reason=${encodeURIComponent(reason)}` : "");
  const res = await fetch(url, { method: "DELETE" });
  if (res.ok || res.status === 204) {
    window.location.href = `/${schema}/${obj}`;
  } else {
    document.getElementById("delete-modal-backdrop").style.display = "none";
    alert("Failed to delete record.");
  }
}

function openPublishModal() {
  document.getElementById("publish-reason").value = "";
  document.getElementById("publish-modal-backdrop").style.display = "flex";
  document.getElementById("publish-reason").focus();
}
function closePublishModal(event) {
  if (event && event.target !== document.getElementById("publish-modal-backdrop")) return;
  document.getElementById("publish-modal-backdrop").style.display = "none";
}
async function submitPublish() {
  const { schema, obj, recordId, requireReason } = _detailCtx;
  const reason = document.getElementById("publish-reason").value.trim();
  if (requireReason && !reason) { alert("A reason is required to publish this record."); return; }
  const url = `/api/records/${schema}/${obj}/${recordId}/publish` + (reason ? `?reason=${encodeURIComponent(reason)}` : "");
  const res = await fetch(url, { method: "POST" });
  if (res.ok) {
    const data = await res.json();
    window.location.href = `/${schema}/${obj}/${data.id}`;
  } else {
    document.getElementById("publish-modal-backdrop").style.display = "none";
    const data = await res.json().catch(() => ({}));
    alert(data.detail || "Failed to publish record.");
  }
}

function openRetireModal() {
  document.getElementById("retire-reason").value = "";
  document.getElementById("retire-modal-backdrop").style.display = "flex";
  document.getElementById("retire-reason").focus();
}
function closeRetireModal(event) {
  if (event && event.target !== document.getElementById("retire-modal-backdrop")) return;
  document.getElementById("retire-modal-backdrop").style.display = "none";
}
async function submitRetire() {
  const { schema, obj, recordId, requireReason } = _detailCtx;
  const reason = document.getElementById("retire-reason").value.trim();
  if (requireReason && !reason) { alert("A reason is required to retire this record."); return; }
  const url = `/api/records/${schema}/${obj}/${recordId}/retire` + (reason ? `?reason=${encodeURIComponent(reason)}` : "");
  const res = await fetch(url, { method: "POST" });
  if (res.ok) {
    window.location.reload();
  } else {
    document.getElementById("retire-modal-backdrop").style.display = "none";
    const data = await res.json().catch(() => ({}));
    alert(data.detail || "Failed to retire record.");
  }
}

// ── Form field validation ─────────────────────────────────────────────────────

function _clearFieldErrors(form) {
  form.querySelectorAll(".input-error").forEach(el => el.classList.remove("input-error"));
  form.querySelectorAll(".form-error").forEach(el => el.remove());
}
function _setFieldError(input, msg) {
  input.classList.add("input-error");
  const div = document.createElement("div");
  div.className = "form-error";
  div.textContent = msg;
  input.insertAdjacentElement("afterend", div);
}
function _validateForm(form) {
  _clearFieldErrors(form);
  let valid = true;
  for (const input of form.querySelectorAll("input[type='number']")) {
    if (input.value === "" && !input.validity.badInput) continue;
    if (!input.validity.valid) {
      _setFieldError(input, input.step === "1" ? "Must be a whole number." : "Must be a valid number.");
      valid = false;
    }
  }
  return valid;
}

// ── Record form page ─────────────────────────────────────────────────────────

async function loadRecordForm(schema, obj, recordId, objConfig) {
  const form = document.getElementById("record-form");
  if (!form) return;

  let record = {};
  if (recordId) {
    const res = await fetch(`/api/records/${schema}/${obj}/${recordId}`);
    if (res.ok) record = await res.json();
  }

  const attrs = Object.entries(objConfig.attributes || {});

  // Separate fields into groups for 2-col pairing
  const pairableFields = [];
  const fullWidthFields = [];

  if (objConfig.parent) {
    fullWidthFields.push({ key: `_${objConfig.parent}_id`, v: { name: objConfig.parent, reference: objConfig.parent }, isParent: true });
  }

  for (const [k, v] of attrs) {
    if (v.reference || v.type === "boolean") {
      fullWidthFields.push({ key: k, v });
    } else {
      pairableFields.push({ key: k, v });
    }
  }

  const makeInput = (key, v, currentVal) => {
    if (v.reference || v.isParent) {
      const colKey = v.isParent ? key : `${key}_id`;
      const refTarget = v.isParent ? objConfig.parent : v.reference;
      return `<div class="mdm-field">
        <label class="mdm-field-label">${escHtml(v.name || key)}</label>
        <select class="mdm-select" name="${colKey}" id="ref-${colKey}" data-reference="${refTarget}">
          <option value="">— select —</option>
        </select>
        ${!v.isParent ? `<span class="mdm-field-hint">References ${escHtml(v.reference)}</span>` : ""}
      </div>`;
    }
    if (v.type === "boolean") {
      const checked = currentVal === true ? " checked" : "";
      return `<div class="mdm-field" style="justify-content:flex-end;padding-top:6px">
        <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--mdm-ink-2);cursor:pointer">
          <input type="checkbox" name="${key}"${checked} style="accent-color:var(--mdm-blue);width:14px;height:14px" />
          ${escHtml(v.name || key)}
        </label>
      </div>`;
    }
    const inputType = v.type === "email" ? "email"
      : v.type === "numeric" || v.type === "integer" ? "number"
      : v.type === "date" ? "date"
      : "text";
    const step = v.type === "integer" ? ' step="1"' : v.type === "numeric" ? ' step="any"' : "";
    const rawVal = currentVal ?? "";
    const val = v.type === "date" && rawVal ? rawVal.slice(0, 10) : rawVal;
    return `<div class="mdm-field">
      <label class="mdm-field-label">${escHtml(v.name || key)}${v.required ? '<span class="req">*</span>' : ""}</label>
      <input class="mdm-input" type="${inputType}" name="${key}" value="${escHtml(val)}"
        ${v.required ? "required" : ""}${step} />
    </div>`;
  };

  // Build paired rows for simple fields, full-width for refs/booleans
  let attrBodyHtml = "";
  for (let i = 0; i < pairableFields.length; i += 2) {
    const a = pairableFields[i];
    const b = pairableFields[i + 1];
    if (b) {
      attrBodyHtml += `<div class="mdm-form-row">
        ${makeInput(a.key, a.v, record[a.key])}
        ${makeInput(b.key, b.v, record[b.key])}
      </div>`;
    } else {
      attrBodyHtml += makeInput(a.key, a.v, record[a.key]);
    }
  }
  for (const { key, v } of fullWidthFields) {
    attrBodyHtml += makeInput(key, v, v.isParent ? record[key] : record[key]);
  }

  const reasonRequired = !!objConfig.require_change_reason;
  const reasonCard = `<div class="mdm-card" style="margin-top:16px">
    <div class="mdm-card-head"><div class="mdm-card-title">Audit</div></div>
    <div class="mdm-card-body">
      <div class="mdm-field">
        <label class="mdm-field-label">Reason for change${reasonRequired ? '<span class="req">*</span>' : ""}</label>
        <input class="mdm-input" type="text" name="_reason" ${reasonRequired ? "required" : ""}
          placeholder="${reasonRequired ? "Required: why is this record being changed?" : "Optional: why is this record being changed?"}" />
        <span class="mdm-field-hint">Stored in the audit log</span>
      </div>
    </div>
  </div>`;

  document.getElementById("form-fields").innerHTML =
    `<div class="mdm-card">
       <div class="mdm-card-head"><div class="mdm-card-title">Attributes</div></div>
       <div class="mdm-card-body"><div class="mdm-form">${attrBodyHtml}</div></div>
     </div>
     ${reasonCard}`;

  await populateRefSelects(schema, objConfig, record);

  for (const input of document.querySelectorAll("#form-fields input[type='number']")) {
    input.addEventListener("blur", () => {
      const field = input.closest(".mdm-field");
      field.querySelectorAll(".input-error").forEach(el => el.classList.remove("input-error"));
      field.querySelectorAll(".form-error").forEach(el => el.remove());
      if (input.value === "" && !input.validity.badInput) return;
      if (!input.validity.valid) {
        _setFieldError(input, input.step === "1" ? "Must be a whole number." : "Must be a valid number.");
      }
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!_validateForm(form)) return;

    const fd = new FormData(form);
    const body = {};
    for (const [k, v] of fd.entries()) {
      if (v !== "") body[k] = v;
    }
    for (const [k, v] of Object.entries(objConfig.attributes || {})) {
      if (v.type === "boolean") body[k] = fd.has(k);
    }

    const method = recordId ? "PUT" : "POST";
    const url = recordId
      ? `/api/records/${schema}/${obj}/${recordId}`
      : `/api/records/${schema}/${obj}`;

    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    if (res.ok) {
      const data = await res.json();
      window.location.href = `/${schema}/${obj}/${data.id || recordId}`;
    } else {
      const err = await res.json().catch(() => ({}));
      let msg = "Failed to save record.";
      if (err.detail) {
        msg = Array.isArray(err.detail) ? err.detail.map(e => e.msg).join("; ") : String(err.detail);
      }
      showAlert(form, msg);
    }
  });
}

async function populateRefSelects(schema, objConfig, record) {
  const selects = document.querySelectorAll("[data-reference]");
  for (const sel of selects) {
    const refObj = sel.dataset.reference;
    const [recsRes, cfgRes] = await Promise.all([
      fetch(`/api/records/${schema}/${refObj}?page_size=500`),
      fetch(`/api/schemas/${schema}/objects/${refObj}`),
    ]);
    if (!recsRes.ok || !cfgRes.ok) continue;
    const data = await recsRes.json();
    const refConfig = await cfgRes.json();
    const dispKeys = Object.entries(refConfig.attributes || {})
      .filter(([, v]) => !v.reference).slice(0, 2).map(([k]) => k);
    const options = data.records.map(r => ({
      value: r._id,
      label: dispKeys.map(k => r[k]).filter(Boolean).join(" – ") || r._id,
      selected: record[sel.name] === r._id,
    }));
    options.sort((a, b) => a.label.localeCompare(b.label));
    for (const opt of options) {
      const el = document.createElement("option");
      el.value = opt.value;
      el.textContent = opt.label;
      if (opt.selected) el.selected = true;
      sel.appendChild(el);
    }
  }
}

// ── History page ─────────────────────────────────────────────────────────────

async function loadHistory(schema, obj, recordId, objConfig, canWrite) {
  const container = document.getElementById("history-container");
  if (!container) return;
  container.innerHTML = `<div style="text-align:center;padding:2rem"><span class="spinner"></span></div>`;

  const res = await fetch(`/api/records/${schema}/${obj}/${recordId}/history`);
  if (!res.ok) {
    container.innerHTML = `<div class="alert alert-error">Failed to load history.</div>`;
    return;
  }
  const history = await res.json();

  if (!history.length) {
    container.innerHTML = `<div class="empty-state"><div class="empty-state__icon">📜</div><div class="empty-state__text">No history found.</div></div>`;
    return;
  }

  const actionBadge = (a) => {
    const cls = { INSERT: "badge-insert", UPDATE: "badge-update", DELETE: "badge-delete", REVERT: "badge-revert" }[a] || "";
    return `<span class="badge ${cls}">${a}</span>`;
  };

  const { maps: refLabelMaps, names: refObjNames } = await _resolveRefLabels(schema, objConfig || {});
  const userAttrs = Object.entries((objConfig || {}).attributes || {});

  const attrSnapshot = (h) => {
    const pairs = [];
    if (objConfig?.parent) {
      const pid = h[`_${objConfig.parent}_id`];
      if (pid != null) {
        const label = refLabelMaps["_parent"]?.[pid] || pid;
        const parentName = refObjNames["_parent"] || objConfig.parent;
        pairs.push(`<span><b>${escHtml(parentName)}:</b> ${escHtml(String(label))}</span>`);
      }
    }
    for (const [k, v] of userAttrs) {
      if (v.reference) {
        const refId = h[`${k}_id`];
        if (refId != null) {
          const label = refLabelMaps[k]?.[refId] || refId;
          pairs.push(`<span><b>${escHtml(v.name || k)}:</b> ${escHtml(String(label))}</span>`);
        }
      } else {
        const val = h[k];
        if (val != null) {
          const displayVal = v.type === "date" ? fmtDateOnly(val) : escHtml(String(val));
          pairs.push(`<span><b>${escHtml(v.name || k)}:</b> ${displayVal}</span>`);
        }
      }
    }
    return pairs.length ? `<div class="history-meta__attrs">${pairs.join("")}</div>` : "";
  };

  const rows = history.map((h) => `<li class="history-item">
    <div class="history-meta">
      <div class="history-meta__version">${actionBadge(h._action)} Version ${h._version}</div>
      <div class="history-meta__time">${fmtDate(h._changed_at)}</div>
      ${h._change_reason ? `<div class="history-meta__reason">Reason: ${escHtml(h._change_reason)}</div>` : ""}
      ${h._changed_by ? `<div class="history-meta__time">By: ${escHtml(h._changed_by)}</div>` : ""}
      ${h._source_system ? `<div class="history-meta__time">Source: ${escHtml(h._source_system)}${h._source_id ? ` / ${escHtml(h._source_id)}` : ""}</div>` : ""}
      ${attrSnapshot(h)}
    </div>
    <div>
      ${canWrite && h._action !== "DELETE" ? `<button class="mdm-btn" style="font-size:12px;height:28px;padding:0 10px"
        title="Restore this record to the values shown in this version."
        onclick="revertToVersion('${schema}','${obj}','${recordId}',${h._version},${!!objConfig.require_change_reason})">Revert</button>` : ""}
    </div>
  </li>`).join("");

  container.innerHTML = `<ul class="history-list">${rows}</ul>`;
}

async function revertToVersion(schema, obj, recordId, version, requireReason = false) {
  const reason = prompt(`Revert to version ${version}? Enter reason (${requireReason ? "required" : "optional"}):`) ?? "";
  if (reason === null) return;
  if (requireReason && !reason.trim()) { alert("A reason is required to revert this record."); return; }
  const res = await fetch(
    `/api/records/${schema}/${obj}/${recordId}/revert/${version}?reason=${encodeURIComponent(reason)}`,
    { method: "POST" }
  );
  if (res.ok) {
    window.location.href = `/${schema}/${obj}/${recordId}`;
  } else {
    alert("Failed to revert.");
  }
}

// ── Export ───────────────────────────────────────────────────────────────────

function exportRecords(schema, obj, format) {
  const state = (typeof recordList !== "undefined" ? recordList.stateValue : null) || "active";
  window.location.href = `/api/records/${schema}/${obj}/export?format=${format}&state=${state}`;
}

// ── Import (moved from list.html inline script) ───────────────────────────────

async function importFile(schema, obj, input) {
  const file = input.files[0];
  if (!file) return;
  const ext = file.name.split(".").pop().toLowerCase();
  const format = ext === "json" ? "json" : ext === "tsv" ? "tsv" : "csv";
  const upsertKey = document.getElementById("upsert-key")?.value || "";
  const fd = new FormData();
  fd.append("file", file);
  const statusEl = document.getElementById("import-status");
  statusEl.innerHTML = `<div class="alert alert-info">Importing…</div>`;

  const initialState = (typeof recordList !== "undefined" && recordList.stateValue === "draft") ? "draft" : "active";
  const importReason = document.getElementById("import-reason")?.value.trim() || "";
  const params = new URLSearchParams({ format, initial_state: initialState });
  if (upsertKey) params.set("upsert_key", upsertKey);
  if (importReason) params.set("reason", importReason);

  const res = await fetch(`/api/records/${schema}/${obj}/import?${params}`, { method: "POST", body: fd });
  const data = await res.json();
  if (res.ok) {
    const parts = [];
    if (data.inserted) parts.push(`${data.inserted} inserted`);
    if (data.updated) parts.push(`${data.updated} updated`);
    const errHtml = data.errors.length
      ? `<br>Errors: ${data.errors.map(e => `Row ${e.row}: ${e.error}`).join("; ")}`
      : "";
    statusEl.innerHTML = `<div class="alert alert-success">${parts.join(", ") || "0 records"}.${errHtml}</div>`;
    if (typeof recordList !== "undefined") recordList.load();
  } else {
    const detail = data.detail;
    let msg;
    if (typeof detail === "object" && detail !== null) {
      const errLines = (detail.errors || []).map(e => `Row ${e.row}: ${e.error}`).join("<br>");
      msg = (detail.detail || "Import failed.") + (errLines ? `<br><br>${errLines}` : "");
    } else {
      msg = detail || "Import failed.";
    }
    statusEl.innerHTML = `<div class="alert alert-error">${msg}</div>`;
  }
  input.value = "";
  // Close import modal after completion
  const importModal = document.getElementById("import-modal");
  if (importModal) importModal.style.display = "none";
}

// ── Audit log page ────────────────────────────────────────────────────────────

let _auditPage = 1;
const _auditPageSize = 50;
let _auditSchemas = [];

function initAuditPage(schemas) {
  _auditSchemas = schemas || [];

  document.getElementById("filter-schema").addEventListener("change", () => { _populateObjDropdown(); loadAuditLog(1); });
  document.getElementById("filter-obj").addEventListener("change", () => loadAuditLog(1));
  document.getElementById("filter-action").addEventListener("change", () => loadAuditLog(1));
  document.getElementById("filter-user").addEventListener("input", () => loadAuditLog(1));
  document.getElementById("filter-from").addEventListener("change", () => loadAuditLog(1));
  document.getElementById("filter-to").addEventListener("change", () => loadAuditLog(1));

  document.getElementById("auth-filter-action").addEventListener("change", () => loadAuthLog(1));
  document.getElementById("auth-filter-user").addEventListener("input", () => loadAuthLog(1));
  document.getElementById("auth-filter-from").addEventListener("change", () => loadAuthLog(1));
  document.getElementById("auth-filter-to").addEventListener("change", () => loadAuthLog(1));

  loadAuditLog(1);
}

function switchAuditTab(name) {
  document.getElementById("tab-data").style.display = name === "data" ? "" : "none";
  document.getElementById("tab-auth").style.display = name === "auth" ? "" : "none";
  document.getElementById("tab-data-btn").classList.toggle("is-on", name === "data");
  document.getElementById("tab-auth-btn").classList.toggle("is-on", name === "auth");
  document.getElementById("audit-total").textContent = "…";
  if (name === "data") loadAuditLog(1);
  else loadAuthLog(1);
}

function _buildObjNameMap(schemas) {
  const map = {};
  for (const s of (schemas || [])) {
    for (const o of (s.objects || [])) {
      map[`${s.name}|${o.key}`] = o.name;
    }
  }
  return map;
}

function _populateObjDropdown() {
  const schemaName = document.getElementById("filter-schema")?.value || "";
  const sel = document.getElementById("filter-obj");
  if (!sel) return;
  sel.innerHTML = '<option value="">All objects</option>';
  const s = _auditSchemas.find((s) => s.name === schemaName);
  for (const o of (s?.objects || [])) {
    const opt = document.createElement("option");
    opt.value = o.key;
    opt.textContent = o.name;
    sel.appendChild(opt);
  }
}

async function loadAuditLog(page) {
  _auditPage = page || 1;
  const tbody = document.getElementById("audit-tbody");
  const totalEl = document.getElementById("audit-total");
  const paginationEl = document.getElementById("audit-pagination");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:2rem"><span class="spinner"></span></td></tr>`;

  const schema = document.getElementById("filter-schema")?.value || "";
  const obj = document.getElementById("filter-obj")?.value || "";
  const action = document.getElementById("filter-action")?.value || "";
  const user = document.getElementById("filter-user")?.value || "";
  const fromTime = document.getElementById("filter-from")?.value || "";
  const toTime = document.getElementById("filter-to")?.value || "";

  const toUtcIso = s => new Date(s).toISOString().replace(/\.\d{3}Z$/, "+00:00");
  const params = new URLSearchParams({ page: _auditPage, page_size: _auditPageSize, exclude_system: "true" });
  if (schema) params.set("schema", schema);
  if (obj) params.set("obj", obj);
  if (action) params.set("action", action);
  if (user) params.set("user", user);
  if (fromTime) params.set("from_time", toUtcIso(fromTime));
  if (toTime) params.set("to_time", toUtcIso(toTime));

  const res = await fetch(`/api/audit?${params}`);
  if (!res.ok) {
    tbody.innerHTML = `<tr><td colspan="7"><div class="alert alert-error">Failed to load audit log.</div></td></tr>`;
    return;
  }
  const data = await res.json();
  if (totalEl) totalEl.textContent = data.total;

  if (!data.records.length) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--mdm-mute)">No entries found.</td></tr>`;
    _renderAuditPagination(paginationEl, data.pages, "loadAuditLog");
    return;
  }

  const objNames = _buildObjNameMap(_auditSchemas);
  const actionBadge = (a) => {
    const cls = { INSERT: "mdm-pill-green", UPDATE: "mdm-pill-blue", DELETE: "mdm-pill-red", REVERT: "mdm-pill-amber" }[a] || "mdm-pill-slate";
    return `<span class="mdm-pill ${cls}">${a}</span>`;
  };

  tbody.innerHTML = data.records.map((r) => {
    const shortId = r.record_id ? r.record_id.slice(0, 8) + "…" : "—";
    const recordLink = r.record_id
      ? `<a href="/${r.schema_name}/${r.object_name}/${r.record_id}/history" title="${escHtml(r.record_id)}" class="mdm-mono" style="font-size:12.5px">${shortId}</a>`
      : "—";
    const objDisplay = objNames[`${r.schema_name}|${r.object_name}`] || r.object_name;
    return `<tr>
      <td class="mdm-mono" style="font-size:12.5px;white-space:nowrap;color:var(--mdm-ink-2)">${fmtDate(r.timestamp)}</td>
      <td><span class="mdm-pill mdm-pill-slate" style="letter-spacing:.06em">${escHtml(r.schema_name.toUpperCase())}</span></td>
      <td title="${escHtml(r.object_name)}">${escHtml(objDisplay)}</td>
      <td>${actionBadge(r.action)}</td>
      <td>${recordLink}</td>
      <td style="font-size:13px">${escHtml(r.user_name || "")}</td>
      <td style="color:var(--mdm-mute);font-size:13px">${escHtml(r.reason || "")}</td>
    </tr>`;
  }).join("");

  _renderAuditPagination(paginationEl, data.pages, "loadAuditLog");
}

async function loadAuthLog(page) {
  _auditPage = page || 1;
  const tbody = document.getElementById("auth-tbody");
  const totalEl = document.getElementById("audit-total");
  const paginationEl = document.getElementById("auth-pagination");
  if (!tbody) return;

  tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:2rem"><span class="spinner"></span></td></tr>`;

  const action = document.getElementById("auth-filter-action")?.value || "";
  const user = document.getElementById("auth-filter-user")?.value || "";
  const fromTime = document.getElementById("auth-filter-from")?.value || "";
  const toTime = document.getElementById("auth-filter-to")?.value || "";

  const toUtcIso = s => new Date(s).toISOString().replace(/\.\d{3}Z$/, "+00:00");
  const params = new URLSearchParams({ page: _auditPage, page_size: _auditPageSize, schema: "_system" });
  if (action) params.set("action", action);
  if (user) params.set("user", user);
  if (fromTime) params.set("from_time", toUtcIso(fromTime));
  if (toTime) params.set("to_time", toUtcIso(toTime));

  const res = await fetch(`/api/audit?${params}`);
  if (!res.ok) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="alert alert-error">Failed to load auth events.</div></td></tr>`;
    return;
  }
  const data = await res.json();
  if (totalEl) totalEl.textContent = data.total;

  if (!data.records.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--mdm-mute)">No entries found.</td></tr>`;
    _renderAuditPagination(paginationEl, data.pages, "loadAuthLog");
    return;
  }

  const authBadge = (a) => {
    const cls = { LOGIN: "mdm-pill-green", LOGIN_FAILED: "mdm-pill-red", LOGOUT: "mdm-pill-slate" }[a] || "mdm-pill-slate";
    return `<span class="mdm-pill ${cls}">${a}</span>`;
  };

  tbody.innerHTML = data.records.map((r) => `<tr>
    <td class="mdm-mono" style="font-size:12.5px;white-space:nowrap;color:var(--mdm-ink-2)">${fmtDate(r.timestamp)}</td>
    <td style="font-size:13px">${escHtml(r.user_name || "")}</td>
    <td>${authBadge(r.action)}</td>
    <td class="mdm-mono" style="font-size:12.5px">${escHtml(r.ip_address || "")}</td>
    <td style="color:var(--mdm-mute);font-size:13px">${escHtml(r.reason || "")}</td>
  </tr>`).join("");

  _renderAuditPagination(paginationEl, data.pages, "loadAuthLog");
}

function _renderAuditPagination(el, pages, fnName) {
  if (!el) return;
  if (pages <= 1) { el.innerHTML = ""; return; }
  let html = `<button ${_auditPage === 1 ? "disabled" : ""} onclick="${fnName}(${_auditPage - 1})">←</button>`;
  for (let p = 1; p <= pages; p++) {
    if (pages > 7 && Math.abs(p - _auditPage) > 2 && p !== 1 && p !== pages) {
      if (p === 2 || p === pages - 1) html += `<span class="pag-ellipsis">…</span>`;
      continue;
    }
    html += `<button class="${p === _auditPage ? "is-on" : ""}" onclick="${fnName}(${p})">${p}</button>`;
  }
  html += `<button ${_auditPage === pages ? "disabled" : ""} onclick="${fnName}(${_auditPage + 1})">→</button>`;
  el.innerHTML = html;
}

// ── User management page (moved from users.html inline script) ────────────────

let _allSchemas = [];
let _users = [];
let _userSortBy = "username";
let _userSortDir = "asc";
let _userSearch = "";

function initUsersPage(allSchemas) {
  _allSchemas = allSchemas;
  loadUsers();
}

function filterUsers() {
  _userSearch = (document.getElementById("user-search")?.value || "").toLowerCase();
  renderUsers();
}

function setUserSort(col) {
  if (_userSortBy === col) {
    _userSortDir = _userSortDir === "asc" ? "desc" : "asc";
  } else {
    _userSortBy = col;
    _userSortDir = "asc";
  }
  renderUsers();
}

function _sortUsers(users) {
  return [...users].sort((a, b) => {
    let av, bv;
    if (_userSortBy === "username") { av = a.username.toLowerCase(); bv = b.username.toLowerCase(); }
    else if (_userSortBy === "role") { av = a.is_admin ? 0 : 1; bv = b.is_admin ? 0 : 1; }
    else if (_userSortBy === "status") { av = a.is_active ? 0 : 1; bv = b.is_active ? 0 : 1; }
    else if (_userSortBy === "created") { av = a.created_at || ""; bv = b.created_at || ""; }
    if (av < bv) return _userSortDir === "asc" ? -1 : 1;
    if (av > bv) return _userSortDir === "asc" ? 1 : -1;
    return 0;
  });
}

function _updateUserSortHeaders() {
  document.querySelectorAll("#users-table .th-sort-icon").forEach(el => { el.textContent = ""; });
  const icon = document.querySelector(`#th-col-${_userSortBy} .th-sort-icon`);
  if (icon) icon.textContent = _userSortDir === "asc" ? " ↑" : " ↓";
}

function _updateUsersMeta(users) {
  const total = users.length;
  const active = users.filter(u => u.is_active).length;
  const admins = users.filter(u => u.is_admin).length;
  const meta = document.getElementById("users-meta");
  if (meta) meta.innerHTML = `<span>${total} users</span><span class="dot"></span><span>${active} active</span><span class="dot"></span><span>${admins} admin${admins !== 1 ? "s" : ""}</span>`;
}

function renderUsers() {
  const tbody = document.getElementById("users-tbody");
  let sorted = _sortUsers(_users);
  if (_userSearch) {
    sorted = sorted.filter(u => u.username.toLowerCase().includes(_userSearch));
  }

  _updateUserSortHeaders();

  if (!sorted.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:var(--mdm-mute)">No users found.</td></tr>';
    return;
  }

  tbody.innerHTML = sorted.map(u => {
    const typePill = u.is_admin
      ? `<span class="mdm-pill mdm-pill-blue">Admin</span>`
      : `<span class="mdm-pill mdm-pill-slate">User</span>`;
    const statusPill = u.is_active
      ? `<span class="mdm-pill mdm-pill-green">Active</span>`
      : `<span class="mdm-pill mdm-pill-slate">Inactive</span>`;

    const ghostActions = `
      <button class="mdm-btn mdm-btn-ghost" style="height:28px;padding:0 10px;font-size:12.5px" onclick="openPasswordModal('${u.id}')">Password</button>
      <button class="mdm-btn mdm-btn-ghost" style="height:28px;padding:0 10px;font-size:12.5px" onclick="generateResetLink('${u.id}')" title="Generate a one-time password reset link valid for 24 hours">Reset link</button>
      ${u.is_active
        ? `<button class="mdm-btn mdm-btn-ghost" style="height:28px;padding:0 10px;font-size:12.5px;color:var(--mdm-red)" onclick="toggleActive('${u.id}', true)">Deactivate</button>`
        : `<button class="mdm-btn mdm-btn-ghost" style="height:28px;padding:0 10px;font-size:12.5px" onclick="toggleActive('${u.id}', false)">Activate</button>`}
      <button class="mdm-btn mdm-btn-icon mdm-btn-ghost" style="height:28px;width:28px" title="More actions"
        onclick="event.stopPropagation();toggleUserMenu('${u.id}')">${_SVG.more}</button>`;

    const userMenu = `<div id="user-menu-${u.id}" style="display:none;position:absolute;top:calc(100% - 4px);right:8px;background:var(--mdm-surface);border:1px solid var(--mdm-border);border-radius:var(--mdm-r-3);box-shadow:var(--mdm-shadow-2);padding:6px;min-width:160px;z-index:20;">
      <button class="tools-menu-item" onclick="toggleAdmin('${u.id}', ${u.is_admin});closeUserMenus()">${u.is_admin ? "Remove admin" : "Make admin"}</button>
    </div>`;

    const expandBtn = u.is_admin
      ? `<span style="width:22px;display:inline-block"></span>`
      : `<button style="width:22px;height:22px;padding:0;border:0;background:transparent;color:var(--mdm-mute);display:inline-flex;align-items:center;justify-content:center;cursor:pointer" onclick="togglePermPanel('${u.id}')" title="Schema permissions" id="expand-btn-${u.id}">${_SVG.chevronRight}</button>`;

    return `
      <tr id="user-row-${u.id}" class="${u.is_active ? "" : "row--inactive"}">
        <td style="text-align:center">${expandBtn}</td>
        <td style="font-weight:500">${escHtml(u.username)}</td>
        <td>${typePill}</td>
        <td>${statusPill}</td>
        <td class="mdm-mono" style="font-size:13px;color:var(--mdm-ink-2)">${u.created_at ? u.created_at.slice(0,10) : "—"}</td>
        <td class="col-actions" style="position:relative">
          <div class="mdm-rowact" id="user-actions-${u.id}" style="display:inline-flex;gap:4px">${ghostActions}</div>
          ${userMenu}
        </td>
      </tr>
      <tr id="perm-panel-${u.id}" class="no-hover" style="display:none">
        <td colspan="6" style="padding:0;background:var(--mdm-surface-2)">
          <div id="perm-panel-content-${u.id}" style="padding:16px 24px 18px">
            <span style="color:var(--mdm-mute);font-size:.85rem">Loading permissions…</span>
          </div>
        </td>
      </tr>`;
  }).join("");
}

async function loadUsers() {
  const res = await fetch("/api/admin/users");
  if (!res.ok) {
    document.getElementById("users-tbody").innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem">Failed to load users.</td></tr>';
    return;
  }
  _users = await res.json();
  _updateUsersMeta(_users);
  renderUsers();
}

async function togglePermPanel(userId) {
  const panel = document.getElementById(`perm-panel-${userId}`);
  const btn = document.getElementById(`expand-btn-${userId}`);
  const actionsDiv = document.getElementById(`user-actions-${userId}`);
  const isOpen = panel.style.display !== "none";
  if (isOpen) {
    panel.style.display = "none";
    if (btn) btn.innerHTML = _SVG.chevronRight;
    if (actionsDiv) actionsDiv.style.opacity = "";
    return;
  }
  panel.style.display = "";
  if (btn) btn.innerHTML = _SVG.chevronDown;
  if (actionsDiv) actionsDiv.style.opacity = "1";
  await loadPermissions(userId);
}

async function loadPermissions(userId) {
  const content = document.getElementById(`perm-panel-content-${userId}`);
  const res = await fetch(`/api/admin/users/${userId}/permissions`);
  if (!res.ok) {
    content.innerHTML = `<div class="mdm-card-body"><span style="color:var(--mdm-red)">Failed to load permissions.</span></div>`;
    return;
  }
  const perms = await res.json();
  const permMap = {};
  perms.forEach(p => { permMap[p.schema_name] = p; });

  const rows = _allSchemas.map(s => {
    const p = permMap[s] || null;
    const hasRead    = p ? p.can_read    : false;
    const hasWrite   = p ? p.can_write   : false;
    const hasPublish = p ? p.can_publish : false;
    const readId    = `perm-read-${userId}-${s}`;
    const writeId   = `perm-write-${userId}-${s}`;
    const publishId = `perm-publish-${userId}-${s}`;
    const roleLabel = hasPublish ? "Publisher" : hasWrite ? "Editor" : hasRead ? "Viewer" : "—";
    const roleCls   = hasPublish ? "mdm-pill-green" : hasWrite ? "mdm-pill-blue" : hasRead ? "mdm-pill-slate" : "";
    return `<tr class="no-hover" style="background:var(--mdm-surface)">
      <td><span class="mdm-pill mdm-pill-slate" style="letter-spacing:.08em">${escHtml(s.toUpperCase())}</span></td>
      <td><label class="mdm-check"><input type="checkbox" id="${readId}" ${hasRead ? "checked" : ""}
            onchange="onReadChange('${userId}','${s}','${readId}','${writeId}','${publishId}')" /> Viewer</label></td>
      <td><label class="mdm-check"><input type="checkbox" id="${writeId}" ${hasWrite ? "checked" : ""}
            onchange="onWriteChange('${userId}','${s}','${readId}','${writeId}','${publishId}')" /> Editor</label></td>
      <td><label class="mdm-check"><input type="checkbox" id="${publishId}" ${hasPublish ? "checked" : ""}
            onchange="onPublishChange('${userId}','${s}','${readId}','${writeId}','${publishId}')" /> Publisher</label></td>
      <td>${roleCls ? `<span class="mdm-pill ${roleCls}">${roleLabel}</span>` : `<span style="color:var(--mdm-mute-2);font-size:13px">—</span>`}</td>
      <td class="col-actions">${p ? `<button class="mdm-btn mdm-btn-ghost" style="height:28px;padding:0 10px;font-size:12.5px;color:var(--mdm-red)" onclick="revokePermission('${userId}','${s}')">Revoke</button>` : ""}</td>
    </tr>`;
  }).join("");

  content.innerHTML = `
    <div style="font-size:11px;font-weight:600;letter-spacing:.06em;color:var(--mdm-mute);text-transform:uppercase;margin-bottom:10px">Schema permissions</div>
    <div style="background:var(--mdm-surface);border:1px solid var(--mdm-border);border-radius:8px;overflow:hidden">
      <table class="mdm-table mdm-table--perm">
        <thead><tr>
          <th style="width:26%">Schema</th>
          <th style="width:18%">Read</th>
          <th style="width:18%">Write</th>
          <th style="width:18%">Publish</th>
          <th>Role</th>
          <th class="col-actions"></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

function onReadChange(userId, schemaName, readId, writeId, publishId) {
  const readEl = document.getElementById(readId);
  const writeEl = document.getElementById(writeId);
  const publishEl = document.getElementById(publishId);
  if (!readEl.checked) { writeEl.checked = false; publishEl.checked = false; }
  _applyPermission(userId, schemaName, readEl.checked, writeEl.checked, publishEl.checked);
}
function onWriteChange(userId, schemaName, readId, writeId, publishId) {
  const readEl = document.getElementById(readId);
  const writeEl = document.getElementById(writeId);
  const publishEl = document.getElementById(publishId);
  if (writeEl.checked) readEl.checked = true;
  if (!writeEl.checked) publishEl.checked = false;
  _applyPermission(userId, schemaName, readEl.checked, writeEl.checked, publishEl.checked);
}
function onPublishChange(userId, schemaName, readId, writeId, publishId) {
  const readEl = document.getElementById(readId);
  const writeEl = document.getElementById(writeId);
  const publishEl = document.getElementById(publishId);
  if (publishEl.checked) { readEl.checked = true; writeEl.checked = true; }
  _applyPermission(userId, schemaName, readEl.checked, writeEl.checked, publishEl.checked);
}
async function _applyPermission(userId, schemaName, canRead, canWrite, canPublish) {
  await fetch(`/api/admin/users/${userId}/permissions/${schemaName}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ can_read: canRead, can_write: canWrite, can_publish: canPublish }),
  });
  await loadPermissions(userId);
}
async function revokePermission(userId, schemaName) {
  await fetch(`/api/admin/users/${userId}/permissions/${schemaName}`, { method: "DELETE" });
  await loadPermissions(userId);
}

function openNewUserModal() {
  document.getElementById("new-user-form").reset();
  document.getElementById("new-user-error").style.display = "none";
  document.getElementById("new-user-modal").style.display = "flex";
}
function openPasswordModal(userId) {
  document.getElementById("pw-user-id").value = userId;
  document.getElementById("pw-new").value = "";
  document.getElementById("pw-error").style.display = "none";
  document.getElementById("pw-modal").style.display = "flex";
}
function closeModal() {
  document.querySelectorAll(".modal-backdrop").forEach(m => m.style.display = "none");
}

async function submitNewUser(e) {
  e.preventDefault();
  const errEl = document.getElementById("new-user-error");
  errEl.style.display = "none";
  const body = {
    username: document.getElementById("nu-username").value.trim(),
    password: document.getElementById("nu-password").value,
    is_admin: document.getElementById("nu-admin").checked,
  };
  const res = await fetch("/api/admin/users", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json();
    errEl.textContent = err.detail || "Failed to create user";
    errEl.style.display = "flex";
    return;
  }
  closeModal();
  loadUsers();
}

async function submitPassword(e) {
  e.preventDefault();
  const userId = document.getElementById("pw-user-id").value;
  const errEl = document.getElementById("pw-error");
  errEl.style.display = "none";
  const res = await fetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: document.getElementById("pw-new").value }),
  });
  if (!res.ok) {
    const err = await res.json();
    errEl.textContent = err.detail || "Failed to update password";
    errEl.style.display = "flex";
    return;
  }
  closeModal();
}

async function toggleAdmin(userId, isAdmin) {
  const res = await fetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_admin: !isAdmin }),
  });
  if (!res.ok) { const e = await res.json(); alert(e.detail || "Failed"); return; }
  loadUsers();
}

async function toggleActive(userId, isActive) {
  const res = await fetch(`/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_active: !isActive }),
  });
  if (!res.ok) { const e = await res.json(); alert(e.detail || "Failed"); return; }
  loadUsers();
}

async function generateResetLink(userId) {
  const res = await fetch(`/api/admin/users/${userId}/reset-link`, { method: "POST" });
  if (!res.ok) { const e = await res.json(); alert(e.detail || "Failed to generate reset link"); return; }
  const data = await res.json();
  document.getElementById("reset-link-url").value = data.reset_url;
  document.getElementById("reset-link-copied").style.display = "none";
  document.getElementById("reset-link-modal").style.display = "flex";
}

function copyResetLink() {
  const input = document.getElementById("reset-link-url");
  navigator.clipboard.writeText(input.value).then(() => {
    document.getElementById("reset-link-copied").style.display = "block";
  }).catch(() => {
    input.select();
    document.execCommand("copy");
    document.getElementById("reset-link-copied").style.display = "block";
  });
}

function toggleUserMenu(userId) {
  const menu = document.getElementById(`user-menu-${userId}`);
  if (!menu) return;
  const isOpen = menu.style.display !== "none";
  closeUserMenus();
  if (!isOpen) menu.style.display = "";
}
function closeUserMenus() {
  document.querySelectorAll('[id^="user-menu-"]').forEach(m => { m.style.display = "none"; });
}

document.addEventListener("click", e => {
  if (e.target.classList.contains("modal-backdrop")) closeModal();
  closeUserMenus();
});
