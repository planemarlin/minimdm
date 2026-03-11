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

    this.load();
  }

  get userAttributes() {
    return Object.entries(this.objConfig.attributes || {}).filter(
      ([, v]) => !v.reference
    );
  }

  async load() {
    if (!this.tbody) return;
    this.tbody.innerHTML = `<tr><td colspan="20" style="text-align:center;padding:2rem"><span class="spinner"></span></td></tr>`;

    const params = new URLSearchParams({
      page: this.page,
      page_size: this.pageSize,
    });
    if (this.search) params.set("search", this.search);

    const res = await fetch(
      `/api/records/${this.schema}/${this.obj}?${params}`
    );
    if (!res.ok) {
      this.tbody.innerHTML = `<tr><td colspan="20"><div class="alert alert-error">Failed to load records.</div></td></tr>`;
      return;
    }
    const data = await res.json();
    this.total = data.total;
    this.renderRows(data.records);
    this.renderPagination(data.pages);
    if (this.totalEl) this.totalEl.textContent = data.total;
  }

  renderRows(records) {
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
    this.tbody.innerHTML = records
      .map((r) => {
        const cells = attrs
          .slice(0, 6)
          .map(([k]) => `<td>${escHtml(r[k] ?? "")}</td>`)
          .join("");
        return `<tr style="cursor:pointer" onclick="window.location='/${schema}/${obj}/${r._id}'">
          ${cells}
          <td class="td-actions" onclick="event.stopPropagation()">
            <a class="btn btn-ghost btn-sm" href="/${schema}/${obj}/${r._id}/edit">Edit</a>
            <button class="btn btn-ghost btn-sm" style="color:var(--danger)"
              onclick="recordList.confirmDelete('${r._id}')">Delete</button>
          </td>
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

  goPage(p) {
    this.page = p;
    this.load();
  }

  async confirmDelete(id) {
    if (!confirm("Delete this record? This action can be undone via history.")) return;
    const reason = prompt("Reason for deletion (optional):") || "";
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

async function loadRecordDetail(schema, obj, recordId, objConfig) {
  const container = document.getElementById("detail-container");
  if (!container) return;

  const res = await fetch(`/api/records/${schema}/${obj}/${recordId}`);
  if (!res.ok) {
    container.innerHTML = `<div class="alert alert-error">Record not found.</div>`;
    return;
  }
  const record = await res.json();

  // Show parent record with a link if configured
  let parentHtml = "";
  if (objConfig.parent) {
    const parentId = record[`_${objConfig.parent}_id`];
    if (parentId) {
      let parentLabel = parentId;
      try {
        const [prRes, pcRes] = await Promise.all([
          fetch(`/api/records/${schema}/${objConfig.parent}/${parentId}`),
          fetch(`/api/schemas/${schema}/objects/${objConfig.parent}`),
        ]);
        if (prRes.ok && pcRes.ok) {
          const pr = await prRes.json();
          const pc = await pcRes.json();
          const dispKeys = Object.entries(pc.attributes || {})
            .filter(([, v]) => !v.reference).slice(0, 2).map(([k]) => k);
          parentLabel = dispKeys.map(k => pr[k]).filter(Boolean).join(" – ") || parentId;
        }
      } catch (_) {}
      parentHtml = `<div class="detail-field">
        <div class="detail-field__label">${escHtml(objConfig.parent)} (parent)</div>
        <div class="detail-field__value">
          <a href="/${schema}/${objConfig.parent}/${parentId}">${escHtml(parentLabel)}</a>
        </div>
      </div>`;
    }
  }

  const attrs = Object.entries(objConfig.attributes || {});
  const fields = attrs
    .map(([k, v]) => {
      const colKey = v.reference ? `${k}_id` : k;
      const val = record[colKey];
      return `<div class="detail-field">
        <div class="detail-field__label">${escHtml(v.name || k)}</div>
        <div class="detail-field__value ${val == null ? "detail-field__value--empty" : ""}">
          ${val != null ? escHtml(String(val)) : "—"}
        </div>
      </div>`;
    })
    .join("");

  const sysMeta = `<div style="margin-top:1.5rem; padding-top:1rem; border-top:1px solid var(--border); font-size:.78rem; color:var(--text-muted); display:flex; gap:1.5rem; flex-wrap:wrap;">
    <span>Created: ${fmtDate(record._created_at)}</span>
    <span>Updated: ${fmtDate(record._updated_at)}</span>
    ${record._created_by ? `<span>By: ${escHtml(record._created_by)}</span>` : ""}
  </div>`;

  container.innerHTML = `<div class="detail-grid">${parentHtml}${fields}</div>${sysMeta}`;
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
      const inputType = v.type === "email" ? "email"
        : v.type === "numeric" || v.type === "integer" ? "number"
        : v.type === "date" ? "date"
        : "text";
      const val = record[k] ?? "";
      return `<div class="form-group">
        <label>${escHtml(v.name || k)}${v.required ? '<span class="required">*</span>' : ""}</label>
        <input type="${inputType}" name="${k}" value="${escHtml(val)}"
          ${v.required ? "required" : ""} />
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

  const reasonField = `<div class="form-group">
    <label>Reason for change</label>
    <input type="text" name="_reason" placeholder="Optional: why is this record being changed?" />
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

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {};
    for (const [k, v] of fd.entries()) {
      if (v !== "") body[k] = v;
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
      showAlert(form, err.detail || "Failed to save record.");
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

    for (const r of data.records) {
      const opt = document.createElement("option");
      opt.value = r._id;
      opt.textContent = dispKeys.map(k => r[k]).filter(Boolean).join(" – ") || r._id;
      if (record[sel.name] === r._id) opt.selected = true;
      sel.appendChild(opt);
    }
  }
}

// ── History page ─────────────────────────────────────────────────────────────

async function loadHistory(schema, obj, recordId) {
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
        </div>
        <div>
          ${h._action !== "DELETE" ? `<button class="btn btn-secondary btn-sm"
            onclick="revertToVersion('${schema}','${obj}','${recordId}',${h._version})">Revert</button>` : ""}
        </div>
      </li>`
    )
    .join("");

  container.innerHTML = `<ul class="history-list">${rows}</ul>`;
}

async function revertToVersion(schema, obj, recordId, version) {
  const reason = prompt(`Revert to version ${version}? Enter reason (optional):`) ?? "";
  if (reason === null) return; // cancelled
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
  window.location.href = `/api/records/${schema}/${obj}/export?format=${format}`;
}
