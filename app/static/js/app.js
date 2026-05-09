/* miniMDM – main JS */

// ── Sidebar toggle (mobile) ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const btn = document.getElementById("menu-btn");
  const sidebar = document.querySelector(".sidebar");
  if (btn && sidebar) {
    btn.addEventListener("click", () => sidebar.classList.toggle("sidebar--open"));
    document.addEventListener("click", (e) => {
      if (!sidebar.contains(e.target) && e.target !== btn) {
        sidebar.classList.remove("sidebar--open");
      }
    });
  }
});

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function escHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function showAlert(container, message, type = "error") {
  const div = document.createElement("div");
  div.className = `alert alert-${type}`;
  div.textContent = message;
  container.prepend(div);
  setTimeout(() => div.remove(), 5000);
}

// ── Reference label resolution ───────────────────────────────────────────────
// Fetches display-label maps for all reference attributes (and the parent, if
// any) defined in objConfig.  Returns an object keyed by attribute name (or
// '_parent' for the parent relationship) whose values are {id -> label} maps.

async function _resolveRefLabels(schema, objConfig) {
  const maps = {};
  const names = {}; // human-readable name for each key's target object
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

    this.tbody = document.getElementById("record-tbody");
    this.paginationEl = document.getElementById("pagination");
    this.totalEl = document.getElementById("total-count");
    this.searchInput = document.getElementById("search-input");
    this.deletedToggle = document.getElementById("show-deleted-toggle");
    this.stateFilter = document.getElementById("state-filter");
    this.includeDeleted = false;
    this.stateValue = "active";

    const firstNonRef = Object.entries(objConfig.attributes || {}).find(([, v]) => !v.reference);
    this.sortBy = firstNonRef ? firstNonRef[0] : null;
    this.sortDir = "asc";

    if (this.searchInput) {
      let timer;
      this.searchInput.addEventListener("input", (e) => {
        clearTimeout(timer);
        timer = setTimeout(() => {
          this.search = e.target.value;
          this.page = 1;
          this.load();
        }, 300);
      });
    }

    if (this.deletedToggle) {
      this.deletedToggle.addEventListener("change", (e) => {
        this.includeDeleted = e.target.checked;
        this.page = 1;
        this.load();
      });
    }

    if (this.stateFilter) {
      this.stateFilter.addEventListener("change", (e) => {
        this.stateValue = e.target.value;
        this.page = 1;
        this.load();
      });
    }

    this.load();
  }

  get userAttributes() {
    return Object.entries(this.objConfig.attributes || {});
  }

  async load() {
    if (!this.tbody) return;
    this.tbody.innerHTML = `<tr><td colspan="20" style="text-align:center;padding:2rem"><span class="spinner"></span></td></tr>`;

    const params = new URLSearchParams({
      page: this.page,
      page_size: this.pageSize,
    });
    if (this.search) params.set("search", this.search);
    if (this.includeDeleted) params.set("include_deleted", "true");
    if (this.stateValue && this.stateValue !== "active") params.set("state", this.stateValue);
    if (this.sortBy) { params.set("sort_by", this.sortBy); params.set("sort_dir", this.sortDir); }

    const res = await fetch(
      `/api/records/${this.schema}/${this.obj}?${params}`
    );
    if (!res.ok) {
      this.tbody.innerHTML = `<tr><td colspan="20"><div class="alert alert-error">Failed to load records.</div></td></tr>`;
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
    this.tbody.innerHTML = records
      .map((r) => {
        const isDeleted = !!r._deleted_at;
        const recordState = r._state || "active";
        const style = isDeleted ? "opacity:.5;text-decoration:line-through" : "";
        const cells = [];
        if (objConfig.parent) {
          const pid = r[`_${objConfig.parent}_id`];
          const label = pid ? (refLabelMaps["_parent"]?.[pid] || pid) : "";
          cells.push(`<td style="${style}">${escHtml(label)}</td>`);
        }
        const remaining = 6 - cells.length;
        for (const [k, v] of attrs.slice(0, remaining)) {
          if (v.reference) {
            const refId = r[`${k}_id`];
            const label = refId ? (refLabelMaps[k]?.[refId] || refId) : "";
            cells.push(`<td style="${style}">${escHtml(label)}</td>`);
          } else {
            cells.push(`<td style="${style}">${escHtml(r[k] ?? "")}</td>`);
          }
        }
        const stateBadge = recordState === "draft"
          ? `<span class="badge badge-draft" style="font-size:.7rem">draft</span>`
          : recordState === "retired"
            ? `<span class="badge badge-retired" style="font-size:.7rem">retired</span>`
            : "";
        const actions = isDeleted
          ? `<a class="btn btn-ghost btn-sm" href="/${schema}/${obj}/${r._id}/history">History</a>
             <span class="badge badge-delete" style="font-size:.7rem">deleted</span>`
          : `<a class="btn btn-ghost btn-sm" href="/${schema}/${obj}/${r._id}/edit">Edit</a>
             <button class="btn btn-ghost btn-sm" style="color:var(--danger)"
               onclick="recordList.confirmDelete('${r._id}')">Delete</button>
             ${stateBadge}`;
        const rowClick = isDeleted
          ? `onclick="window.location='/${schema}/${obj}/${r._id}/history'"`
          : `onclick="window.location='/${schema}/${obj}/${r._id}'"`;
        return `<tr style="cursor:pointer" ${rowClick}>
          ${cells.join("")}
          <td class="td-actions" onclick="event.stopPropagation()">${actions}</td>
        </tr>`;
      })
      .join("");
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

  goPage(p) {
    this.page = p;
    this.load();
  }

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

async function loadRecordDetail(schema, obj, recordId, objConfig, opts = {}) {
  const container = document.getElementById("detail-container");
  if (!container) return;

  const res = await fetch(`/api/records/${schema}/${obj}/${recordId}?include_deleted=true`);
  if (!res.ok) {
    container.innerHTML = `<div class="alert alert-error">Record not found.</div>`;
    return;
  }
  const record = await res.json();

  // Show/hide lifecycle action buttons based on record state and user permissions
  const recordState = record._state || "active";
  const publishBtn = document.getElementById("btn-publish");
  const retireBtn = document.getElementById("btn-retire");
  const editBtn = document.getElementById("btn-edit");
  const deleteBtn = document.getElementById("btn-delete");
  if (publishBtn) publishBtn.style.display = (opts.canPublish && recordState === "draft") ? "" : "none";
  if (retireBtn) retireBtn.style.display = (opts.canPublish && recordState === "active") ? "" : "none";
  if (editBtn) editBtn.style.display = (opts.canWrite && recordState !== "retired") ? "" : "none";
  if (deleteBtn) deleteBtn.style.display = (opts.canWrite && recordState !== "retired") ? "" : "none";

  // Show parent record with a link if configured
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
      const deletedBadge = parentDeleted ? ' <span class="badge badge-delete">deleted</span>' : "";
      parentHtml = `<div class="detail-field">
        <div class="detail-field__label">${escHtml(objConfig.parent)} (parent)</div>
        <div class="detail-field__value">
          ${parentDeleted
            ? `${escHtml(parentLabel)}${deletedBadge}`
            : `<a href="/${schema}/${objConfig.parent}/${parentId}">${escHtml(parentLabel)}</a>`}
        </div>
      </div>`;
    }
  }

  // Resolve reference fields: fetch referenced records (including deleted) in parallel
  const attrs = Object.entries(objConfig.attributes || {});
  const refResolved = {};
  await Promise.all(
    attrs
      .filter(([, v]) => v.reference)
      .map(async ([k, v]) => {
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

  const fields = attrs
    .map(([k, v]) => {
      if (v.reference) {
        const refId = record[`${k}_id`];
        if (!refId) {
          return `<div class="detail-field">
            <div class="detail-field__label">${escHtml(v.name || k)}</div>
            <div class="detail-field__value detail-field__value--empty">—</div>
          </div>`;
        }
        const ref = refResolved[k];
        const label = ref ? ref.label : refId;
        const valueHtml = ref && ref.deleted
          ? `${escHtml(label)} <span class="badge badge-delete">deleted</span>`
          : ref
            ? `<a href="/${schema}/${ref.obj}/${refId}">${escHtml(label)}</a>`
            : escHtml(String(refId));
        return `<div class="detail-field">
          <div class="detail-field__label">${escHtml(v.name || k)}</div>
          <div class="detail-field__value">${valueHtml}</div>
        </div>`;
      }
      const val = record[k];
      return `<div class="detail-field">
        <div class="detail-field__label">${escHtml(v.name || k)}</div>
        <div class="detail-field__value ${val == null ? "detail-field__value--empty" : ""}">
          ${val != null ? escHtml(String(val)) : "—"}
        </div>
      </div>`;
    })
    .join("");

  const stateLabel = { active: "Active", draft: "Draft", retired: "Retired" }[recordState] || recordState;
  const stateBadgeHtml = recordState === "draft"
    ? `<span class="badge badge-draft">${stateLabel}</span>`
    : recordState === "retired"
      ? `<span class="badge badge-retired">${stateLabel}</span>`
      : `<span class="badge badge-insert" style="background:var(--success,#2a9d5c)">${stateLabel}</span>`;
  const sysMeta = `<div style="margin-top:1.5rem; padding-top:1rem; border-top:1px solid var(--border); font-size:.78rem; color:var(--text-muted); display:flex; gap:1.5rem; flex-wrap:wrap; align-items:center">
    ${stateBadgeHtml}
    <span>Created: ${fmtDate(record._created_at)}</span>
    <span>Updated: ${fmtDate(record._updated_at)}</span>
    ${record._created_by ? `<span>By: ${escHtml(record._created_by)}</span>` : ""}
  </div>`;

  container.innerHTML = `<div class="detail-grid">${parentHtml}${fields}</div>${sysMeta}`;

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

  // Parent-child panels
  const childObjects = Object.entries(schemaConfig.objects || {})
    .filter(([, cfg]) => cfg.parent === parentObj);

  // Reference panels: objects with a reference attribute pointing to parentObj
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
    const panel = document.createElement("details");
    panel.className = "related-panel";
    panel.open = true;

    const summary = document.createElement("summary");
    summary.className = "related-panel__summary";
    summary.innerHTML = `${escHtml(label || childCfg.name || childKey)}<span class="related-panel__count">loading…</span>`;
    panel.appendChild(summary);

    const body = document.createElement("div");
    body.className = "related-panel__body";
    body.innerHTML = `<div style="padding:.75rem 1rem;font-size:.85rem;color:var(--text-muted)"><span class="spinner"></span></div>`;
    panel.appendChild(body);
    container.appendChild(panel);

    try {
      const [recsRes, cfgRes] = await Promise.all([
        fetch(`/api/records/${schema}/${childKey}?` + params),
        fetch(`/api/schemas/${schema}/objects/${childKey}`),
      ]);
      if (!recsRes.ok) { body.innerHTML = `<div class="alert alert-error" style="margin:.75rem">Failed to load records.</div>`; continue; }
      const data = await recsRes.json();
      const refCfg = cfgRes.ok ? await cfgRes.json() : {};

      summary.querySelector(".related-panel__count").textContent =
        `${data.total} record${data.total !== 1 ? "s" : ""}`;

      if (!data.total) {
        body.innerHTML = `<div style="padding:.75rem 1rem;font-size:.85rem;color:var(--text-muted)">No records.</div>`;
        continue;
      }

      const cols = Object.entries(refCfg.attributes || {})
        .filter(([, v]) => !v.reference)
        .slice(0, 4);

      const thead = `<thead><tr>${cols.map(([k, v]) => `<th>${escHtml(v.name || k)}</th>`).join("")}<th></th></tr></thead>`;
      const tbody = data.records.map(r => {
        const cells = cols.map(([k]) => `<td>${escHtml(String(r[k] ?? ""))}</td>`).join("");
        return `<tr style="cursor:pointer" onclick="window.location.href='/${schema}/${childKey}/${r._id}'">${cells}<td style="text-align:right"><a href="/${schema}/${childKey}/${r._id}" class="btn btn-sm btn-secondary" onclick="event.stopPropagation()">View</a></td></tr>`;
      }).join("");

      body.innerHTML = `<div class="table-wrap"><table>${thead}<tbody>${tbody}</tbody></table></div>`;
    } catch (_) {
      body.innerHTML = `<div class="alert alert-error" style="margin:.75rem">Failed to load records.</div>`;
    }
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
    // When non-numeric text is typed, browsers set value="" but badInput=true.
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
  const fieldsHtml = attrs
    .map(([k, v]) => {
      if (v.reference) {
        const colKey = `${k}_id`;
        return `<div class="form-group">
          <label>${escHtml(v.name || k)}</label>
          <select name="${colKey}" id="ref-${colKey}" data-reference="${v.reference}">
            <option value="">— select —</option>
          </select>
          <div class="form-hint">References ${v.reference}</div>
        </div>`;
      }
      if (v.type === "boolean") {
        const checked = record[k] === true ? " checked" : "";
        return `<div class="form-group">
          <label class="checkbox-label">
            <input type="checkbox" name="${k}"${checked} />
            ${escHtml(v.name || k)}
          </label>
        </div>`;
      }
      const inputType = v.type === "email" ? "email"
        : v.type === "numeric" || v.type === "integer" ? "number"
        : v.type === "date" ? "date"
        : "text";
      const step = v.type === "integer" ? ' step="1"' : v.type === "numeric" ? ' step="any"' : "";
      const rawVal = record[k] ?? "";
      const val = v.type === "date" && rawVal ? rawVal.slice(0, 10) : rawVal;
      return `<div class="form-group">
        <label>${escHtml(v.name || k)}${v.required ? '<span class="required">*</span>' : ""}</label>
        <input type="${inputType}" name="${k}" value="${escHtml(val)}"
          ${v.required ? "required" : ""}${step} />
      </div>`;
    })
    .join("");

  const parentField = objConfig.parent
    ? `<div class="form-group">
        <label>${escHtml(objConfig.parent)} (parent)</label>
        <select name="_${objConfig.parent}_id" id="ref-parent" data-reference="${objConfig.parent}">
          <option value="">— select —</option>
        </select>
      </div>`
    : "";

  const reasonRequired = !!objConfig.require_change_reason;
  const reasonField = `<div class="form-group">
    <label>Reason for change${reasonRequired ? ' <span style="color:var(--danger)">*</span>' : ''}</label>
    <input type="text" name="_reason" ${reasonRequired ? 'required' : ''} placeholder="${reasonRequired ? 'Required: why is this record being changed?' : 'Optional: why is this record being changed?'}" />
    <div class="form-hint">Stored in the audit log</div>
  </div>`;

  document.getElementById("form-fields").innerHTML =
    `<div class="form-section">
       <div class="form-section__title">Attributes</div>
       ${parentField}${fieldsHtml}
     </div>
     <div class="form-section">
       <div class="form-section__title">Audit</div>
       ${reasonField}
     </div>`;

  // Populate reference selects
  await populateRefSelects(schema, objConfig, record);

  // Blur-time numeric validation
  for (const input of document.querySelectorAll("#form-fields input[type='number']")) {
    input.addEventListener("blur", () => {
      const group = input.closest(".form-group");
      group.querySelectorAll(".input-error").forEach(el => el.classList.remove("input-error"));
      group.querySelectorAll(".form-error").forEach(el => el.remove());
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
    // Checkboxes for boolean fields are absent from FormData when unchecked —
    // explicitly set true/false so the API receives a JSON boolean, not a string.
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
      const id = data.id || recordId;
      window.location.href = `/${schema}/${obj}/${id}`;
    } else {
      const err = await res.json().catch(() => ({}));
      let msg = "Failed to save record.";
      if (err.detail) {
        msg = Array.isArray(err.detail)
          ? err.detail.map(e => e.msg).join("; ")
          : String(err.detail);
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

    // Show first two non-reference attributes as "code – name" style label
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
          pairs.push(`<span><b>${escHtml(v.name || k)}:</b> ${escHtml(String(val))}</span>`);
        }
      }
    }
    return pairs.length ? `<div class="history-meta__attrs">${pairs.join("")}</div>` : "";
  };

  const rows = history
    .map(
      (h) => `<li class="history-item">
        <div class="history-meta">
          <div class="history-meta__version">
            ${actionBadge(h._action)} Version ${h._version}
          </div>
          <div class="history-meta__time">${fmtDate(h._changed_at)}</div>
          ${h._change_reason ? `<div class="history-meta__reason">Reason: ${escHtml(h._change_reason)}</div>` : ""}
          ${h._changed_by ? `<div class="history-meta__time">By: ${escHtml(h._changed_by)}</div>` : ""}
          ${attrSnapshot(h)}
        </div>
        <div>
          ${canWrite && h._action !== "DELETE" ? `<button class="btn btn-secondary btn-sm"
            title="Restore this record to the values shown in this version."
            onclick="revertToVersion('${schema}','${obj}','${recordId}',${h._version},${!!objConfig.require_change_reason})">Revert</button>` : ""}
        </div>
      </li>`
    )
    .join("");

  container.innerHTML = `<ul class="history-list">${rows}</ul>`;
}

async function revertToVersion(schema, obj, recordId, version, requireReason = false) {
  const reason = prompt(`Revert to version ${version}? Enter reason (${requireReason ? "required" : "optional"}):`) ?? "";
  if (reason === null) return; // cancelled
  if (requireReason && !reason.trim()) {
    alert("A reason is required to revert this record.");
    return;
  }
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
  const stateEl = document.getElementById("state-filter");
  const state = stateEl ? stateEl.value : "active";
  window.location.href = `/api/records/${schema}/${obj}/export?format=${format}&state=${state}`;
}

// ── Audit log page ────────────────────────────────────────────────────────────

let _auditPage = 1;
const _auditPageSize = 50;

// Build a display-name lookup from the schemas array injected by the audit template.
// Key: "schema_name|object_key" → display name. Falls back to the key for removed objects.
function _buildObjNameMap(schemas) {
  const map = {};
  for (const s of (schemas || [])) {
    for (const o of (s.objects || [])) {
      map[`${s.name}|${o.key}`] = o.name;
    }
  }
  return map;
}

// Populate the object filter dropdown based on the currently selected schema.
function _populateObjDropdown() {
  const schemas = typeof _auditSchemas !== "undefined" ? _auditSchemas : [];
  const schemaName = document.getElementById("filter-schema")?.value || "";
  const sel = document.getElementById("filter-obj");
  if (!sel) return;
  sel.innerHTML = '<option value="">All objects</option>';
  const s = schemas.find((s) => s.name === schemaName);
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
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:2rem;color:var(--text-muted)">No entries found.</td></tr>`;
    _renderAuditPagination(paginationEl, data.pages, "loadAuditLog");
    return;
  }

  const schemas = typeof _auditSchemas !== "undefined" ? _auditSchemas : [];
  const objNames = _buildObjNameMap(schemas);

  const actionBadge = (a) => {
    const cls = { INSERT: "badge-insert", UPDATE: "badge-update", DELETE: "badge-delete", REVERT: "badge-revert" }[a] || "";
    return `<span class="badge ${cls}">${a}</span>`;
  };

  tbody.innerHTML = data.records.map((r) => {
    const shortId = r.record_id ? r.record_id.slice(0, 8) + "…" : "—";
    const recordLink = r.record_id
      ? `<a href="/${r.schema_name}/${r.object_name}/${r.record_id}/history"
            title="${escHtml(r.record_id)}" style="font-family:monospace">${shortId}</a>`
      : "—";
    const objDisplay = objNames[`${r.schema_name}|${r.object_name}`] || r.object_name;
    return `<tr>
      <td style="white-space:nowrap;font-size:.85rem">${fmtDate(r.timestamp)}</td>
      <td>${escHtml(r.schema_name)}</td>
      <td title="${escHtml(r.object_name)}">${escHtml(objDisplay)}</td>
      <td>${actionBadge(r.action)}</td>
      <td>${recordLink}</td>
      <td style="font-size:.85rem">${escHtml(r.user_name || "")}</td>
      <td style="color:var(--text-muted);font-size:.85rem">${escHtml(r.reason || "")}</td>
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
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--text-muted)">No entries found.</td></tr>`;
    _renderAuditPagination(paginationEl, data.pages, "loadAuthLog");
    return;
  }

  const authBadge = (a) => {
    const cls = { LOGIN: "badge-insert", LOGIN_FAILED: "badge-delete", LOGOUT: "badge-update" }[a] || "";
    return `<span class="badge ${cls}">${a}</span>`;
  };

  tbody.innerHTML = data.records.map((r) => `<tr>
    <td style="white-space:nowrap;font-size:.85rem">${fmtDate(r.timestamp)}</td>
    <td>${escHtml(r.user_name || "")}</td>
    <td>${authBadge(r.action)}</td>
    <td style="font-family:monospace;font-size:.85rem">${escHtml(r.ip_address || "")}</td>
    <td style="color:var(--text-muted);font-size:.85rem">${escHtml(r.reason || "")}</td>
  </tr>`).join("");

  _renderAuditPagination(paginationEl, data.pages, "loadAuthLog");
}

function _renderAuditPagination(el, pages, fnName) {
  if (!el) return;
  if (pages <= 1) { el.innerHTML = ""; return; }

  let html = `<button class="page-btn" ${_auditPage === 1 ? "disabled" : ""}
    onclick="${fnName}(${_auditPage - 1})">&#8592;</button>`;

  for (let p = 1; p <= pages; p++) {
    if (pages > 7 && Math.abs(p - _auditPage) > 2 && p !== 1 && p !== pages) {
      if (p === 2 || p === pages - 1) html += `<span style="padding:0 .3rem">…</span>`;
      continue;
    }
    html += `<button class="page-btn ${p === _auditPage ? "page-btn--active" : ""}"
      onclick="${fnName}(${p})">${p}</button>`;
  }

  html += `<button class="page-btn" ${_auditPage === pages ? "disabled" : ""}
    onclick="${fnName}(${_auditPage + 1})">&#8594;</button>`;
  el.innerHTML = html;
}
