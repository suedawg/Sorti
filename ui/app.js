/**
 * Sorti Frontend Application Logic.
 * Manages live folder taxonomy, incoming files, quick-search destination picker, and undo actions.
 */

let activeTaxonomy = [];
let allDestinationOptions = [];
let fileDestOverrides = {}; // { "file.docx": "Course/Subfolder" }
let currentPickerFile = null;
let latestStatusData = null;

document.addEventListener("DOMContentLoaded", () => {
  loadAll();
  checkUpdate();
  // Poll every 5 seconds for new downloads in root folder
  setInterval(loadStatus, 5000);
  setInterval(checkUpdate, 15 * 60 * 1000);

  // Close modals on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      closeDestPicker();
      closeCreateFolderModal();
    }
  });
});

async function loadAll() {
  await loadTaxonomy();
  await loadStatus();
}

async function loadStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();
    latestStatusData = data;

    if (data.ready === false) {
      const rootEl = document.getElementById("studyRootLabel");
      if (rootEl) rootEl.innerText = `⚡ ${data.message || "Initializing Sorti Engine..."}`;
      setTimeout(loadAll, 350);
      return;
    }

    // Update Header Labels
    document.getElementById("studyRootLabel").innerText = `Study Root: ${data.study_root}`;
    document.getElementById("incomingCountTotal").innerText = data.incoming_count + (data.unsorted_count || 0);
    const readyToSweepCount = (data.incoming_files || []).filter(f => f.is_auto_sort || fileDestOverrides[f.filename]).length;
    document.getElementById("autoCountBadge").innerText = readyToSweepCount;

    // Triage Indicator & Section
    const triagePill = document.getElementById("triageIndicator");
    const triageSection = document.getElementById("triageSection");
    const triageCountText = document.getElementById("triageCountText");

    // All files needing triage: files in _Unsorted + ambiguous incoming files
    const allTriageFiles = [
      ...(data.unsorted_files || []),
      ...(data.incoming_files || []).filter(f => !f.is_auto_sort)
    ];

    if (allTriageFiles.length > 0) {
      triagePill.classList.remove("hidden");
      triageSection.classList.remove("hidden");
      triageCountText.innerText = `${allTriageFiles.length} File${allTriageFiles.length > 1 ? 's' : ''} Need Direction`;
      renderTriageList(allTriageFiles);
    } else {
      triagePill.classList.add("hidden");
      triageSection.classList.add("hidden");
    }

    // Render Main Incoming Files List
    renderIncomingFiles(data.incoming_files || []);

    // Render History & Undo Button
    renderHistory(data.history || []);
    document.getElementById("undoBtn").disabled = !(data.history && data.history.length > 0);

  } catch (err) {
    console.error("Failed to load status:", err);
  }
}

async function loadTaxonomy() {
  try {
    const res = await fetch("/api/taxonomy");
    if (!res.ok) return;
    const data = await res.json();
    activeTaxonomy = data.tree || [];

    // Build flattened destination options list for quick lookups
    allDestinationOptions = [];
    activeTaxonomy.forEach(course => {
      allDestinationOptions.push({ label: course.name, value: course.name });
      if (course.subfolders) {
        course.subfolders.forEach(sub => {
          allDestinationOptions.push({
            label: `${course.name} → ${sub.name}`,
            value: `${course.name}/${sub.name}`
          });
        });
      }
    });

    renderCourseTree(activeTaxonomy);
  } catch (err) {
    console.error("Failed to load taxonomy:", err);
  }
}

function renderCourseTree(courses) {
  const container = document.getElementById("courseTreeContainer");
  if (!courses || courses.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        No courses found on disk yet.<br>
        Click <strong>"+ New Course"</strong> above to set up your first subject.
      </div>`;
    return;
  }

  container.innerHTML = courses.map(course => {
    const subfolderItems = (course.subfolders || []).map(sub => `
      <div class="subfolder-item">
        <span>📁 ${escapeHtml(sub.name)}</span>
        <span class="file-count-badge">${sub.file_count} file${sub.file_count !== 1 ? 's' : ''}</span>
      </div>
    `).join("");

    return `
      <div class="course-card">
        <div class="course-header">
          <div class="course-name-group">
            <svg class="course-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
            </svg>
            <span class="course-name">${escapeHtml(course.name)}</span>
          </div>
          <span class="file-count-badge">${course.file_count} root file${course.file_count !== 1 ? 's' : ''}</span>
        </div>

        <div class="subfolder-list">
          ${subfolderItems}
          <button class="add-subfolder-btn" onclick="openCreateSubfolderModal('${escapeJsString(course.name)}')">
            + Add Topic/Seminar
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function renderTriageList(triageFiles) {
  const container = document.getElementById("triageList");
  if (!triageFiles || triageFiles.length === 0) {
    container.innerHTML = "";
    return;
  }

  container.innerHTML = triageFiles.map((file) => {
    const overrideDest = fileDestOverrides[file.filename];
    const bestMatch = file.best_match;
    const dest = overrideDest || (bestMatch ? bestMatch.destination : "");
    const isOverridden = Boolean(overrideDest);

    return `
      <div class="triage-item-card">
        <div class="triage-item-top">
          <div class="triage-filename">📄 ${escapeHtml(file.filename)}${file.ocr_fallback ? '<span class="ocr-chip">OCR p.1</span>' : ''}</div>
          <span class="destination-tag dest-tag-clickable ${isOverridden ? 'dest-override-pill' : 'tag-triage'}"
                onclick="openDestPickerForFile('${escapeJsString(file.filename)}')">
            ${dest ? `→ ${escapeHtml(dest)}` : '📁 Select Destination...'} ✏️
          </span>
        </div>
        ${file.snippet ? `<div class="triage-snippet">"${escapeHtml(file.snippet)}"</div>` : ''}
        <div class="triage-actions" style="margin-top: 10px; display: flex; align-items: center; gap: 10px;">
          <button class="btn btn-sm btn-outline" onclick="openDestPickerForFile('${escapeJsString(file.filename)}')">
            Change Destination
          </button>
          <button class="btn btn-sm btn-primary" onclick="resolveTriageDirect('${escapeJsString(file.filename)}', '${escapeJsString(dest)}')">
            Convert & Sort
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function renderIncomingFiles(files) {
  const container = document.getElementById("incomingFilesContainer");
  if (!files || files.length === 0) {
    container.innerHTML = `<div class="empty-state">No unsorted files in main folder. Everything is organized!</div>`;
    return;
  }

  container.innerHTML = files.map(file => {
    const isAuto = file.is_auto_sort && file.best_match;
    const overrideDest = fileDestOverrides[file.filename];
    const dest = overrideDest || (isAuto ? file.best_match.destination : "Requires Triage");
    const isOverridden = Boolean(overrideDest);

    return `
      <div class="incoming-item">
        <div class="file-info-group">
          <svg class="file-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
          </svg>
          <div>
            <div class="file-name">${escapeHtml(file.filename)}${file.ocr_fallback ? '<span class="ocr-chip">OCR p.1</span>' : ''}</div>
            ${file.snippet ? `<div style="font-size: 11px; color: var(--text-muted); max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(file.snippet)}</div>` : ''}
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <span class="destination-tag dest-tag-clickable ${isOverridden ? 'dest-override-pill' : (isAuto ? 'tag-auto' : 'tag-triage')}"
                onclick="openDestPickerForFile('${escapeJsString(file.filename)}')">
            → ${escapeHtml(dest)} ${isOverridden ? '(Manual)' : (isAuto ? `(${Math.round(file.best_match.confidence * 100)}%)` : '')} ✏️
          </span>
          ${(isAuto || isOverridden) ? `
            <button class="btn btn-sm btn-secondary" onclick="singleSort('${escapeJsString(file.filename)}', '${escapeJsString(dest)}')">
              Sort
            </button>
          ` : `
            <button class="btn btn-sm btn-outline" onclick="openDestPickerForFile('${escapeJsString(file.filename)}')">
              Direct
            </button>
          `}
        </div>
      </div>
    `;
  }).join("");
}

function renderHistory(history) {
  const container = document.getElementById("historyList");
  if (!history || history.length === 0) {
    container.innerHTML = `<div class="history-empty">No recent sorting operations.</div>`;
    return;
  }

  container.innerHTML = history.slice().reverse().map(item => `
    <div class="history-item">
      <span>Sorted <strong>${escapeHtml(item.original_name)}</strong> → <code>${escapeHtml(item.destination_rel)}</code></span>
      <span style="font-size: 11px; color: var(--text-muted);">${new Date(item.timestamp).toLocaleTimeString()}</span>
    </div>
  `).join("");
}

/* Quick-Search Destination Picker Logic */
function openDestPickerForFile(filename) {
  const allFiles = [
    ...(latestStatusData?.incoming_files || []),
    ...(latestStatusData?.unsorted_files || [])
  ];
  const file = allFiles.find(f => f.filename === filename);
  if (!file) {
    // If not found in cache, construct fallback file object
    currentPickerFile = { filename, best_match: null, candidates: [] };
  } else {
    currentPickerFile = file;
  }

  document.getElementById("pickerFileName").innerText = filename;

  // Render AI Top Alternative Matches
  const aiSection = document.getElementById("pickerAiSection");
  const aiChips = document.getElementById("pickerAiChips");
  const candidates = currentPickerFile.candidates || (currentPickerFile.best_match ? [currentPickerFile.best_match] : []);

  if (candidates && candidates.length > 0) {
    aiSection.classList.remove("hidden");
    aiChips.innerHTML = candidates.map(c => `
      <button class="picker-chip" onclick="applyPickerDestination('${escapeJsString(c.destination)}')">
        <span>⚡ → ${escapeHtml(c.destination)}</span>
        <span style="opacity: 0.75; font-size: 11px;">(${Math.round(c.confidence * 100)}%)</span>
      </button>
    `).join("");
  } else {
    aiSection.classList.add("hidden");
  }

  // Clear filter input & render hierarchical tree
  const searchInput = document.getElementById("destSearchInput");
  searchInput.value = "";
  renderDestPickerTree("");

  // Show modal
  document.getElementById("destPickerModal").classList.remove("hidden");
  setTimeout(() => searchInput.focus(), 80);
}

function closeDestPicker() {
  document.getElementById("destPickerModal").classList.add("hidden");
  currentPickerFile = null;
}

function filterDestPickerTree() {
  const query = document.getElementById("destSearchInput").value.trim().toLowerCase();
  renderDestPickerTree(query);
}

function renderDestPickerTree(filterQuery) {
  const container = document.getElementById("destTreeList");
  if (!activeTaxonomy || activeTaxonomy.length === 0) {
    container.innerHTML = `<div class="empty-state">No courses found on disk.</div>`;
    return;
  }

  let html = "";
  activeTaxonomy.forEach(course => {
    const courseNameLower = course.name.toLowerCase();
    const subfolders = course.subfolders || [];

    // Filter subfolders
    const matchedSubs = subfolders.filter(sub => {
      if (!filterQuery) return true;
      return sub.name.toLowerCase().includes(filterQuery) || courseNameLower.includes(filterQuery);
    });

    const courseMatches = !filterQuery || courseNameLower.includes(filterQuery) || matchedSubs.length > 0;

    if (!courseMatches) return;

    const subRowsHtml = matchedSubs.map(sub => {
      const fullPath = `${course.name}/${sub.name}`;
      return `
        <div class="picker-subfolder-row" onclick="applyPickerDestination('${escapeJsString(fullPath)}')">
          <span>📁 ${escapeHtml(sub.name)}</span>
          <span style="font-size: 11px; color: var(--text-muted);">${sub.file_count || 0} file(s)</span>
        </div>
      `;
    }).join("");

    html += `
      <div class="picker-course-group">
        <div class="picker-course-row" onclick="applyPickerDestination('${escapeJsString(course.name)}')">
          <span>📚 ${escapeHtml(course.name)}</span>
          <span class="picker-course-select-badge">Select Course Root</span>
        </div>
        ${subRowsHtml ? `<div class="picker-subfolders-container">${subRowsHtml}</div>` : ''}
      </div>
    `;
  });

  if (!html) {
    html = `
      <div class="empty-state" style="padding: 16px;">
        No folders match "<strong>${escapeHtml(filterQuery)}</strong>".<br>
        <button class="btn btn-sm btn-outline" style="margin-top: 8px;" onclick="closeDestPicker(); openCreateFolderModal();">
          + Create New Folder "${escapeHtml(filterQuery)}"
        </button>
      </div>
    `;
  }

  container.innerHTML = html;
}

function applyPickerDestination(destination) {
  if (!currentPickerFile) return;
  const filename = currentPickerFile.filename;
  fileDestOverrides[filename] = destination;
  closeDestPicker();
  showToast(`Destination updated: ${destination}`);

  // Re-render UI views immediately
  renderIncomingFiles(latestStatusData?.incoming_files || []);
  const allTriageFiles = [
    ...(latestStatusData?.unsorted_files || []),
    ...(latestStatusData?.incoming_files || []).filter(f => !f.is_auto_sort)
  ];
  renderTriageList(allTriageFiles);

  // Update badge count to include the user's manual override
  const readyToSweepCount = (latestStatusData?.incoming_files || []).filter(f => f.is_auto_sort || fileDestOverrides[f.filename]).length;
  document.getElementById("autoCountBadge").innerText = readyToSweepCount;
}

async function sortAllAuto() {
  const btn = document.getElementById("sortAllBtn");
  btn.disabled = true;
  btn.innerText = "Sweeping...";

  try {
    const res = await fetch("/api/intake/sweep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ overrides: fileDestOverrides })
    });
    const data = await res.json();
    let msg = `Swept intake: ${data.sorted_count} file(s) sorted.`;
    if (data.unsorted_count > 0) {
      msg += ` ${data.unsorted_count} ambiguous file(s) staged in _Unsorted for triage.`;
    }
    showToast(msg);
    fileDestOverrides = {};
    await loadAll();
  } catch (err) {
    showToast(`Error during sweep: ${err}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polyline></svg> ⚡ Sweep Intake (<span id="autoCountBadge">0</span>)`;
    const readyToSweepCount = (latestStatusData?.incoming_files || []).filter(f => f.is_auto_sort || fileDestOverrides[f.filename]).length;
    document.getElementById("autoCountBadge").innerText = readyToSweepCount;
  }
}

async function singleSort(filename, destination) {
  try {
    const res = await fetch("/api/triage/resolve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, destination })
    });
    const data = await res.json();
    if (data.success) {
      delete fileDestOverrides[filename];
      showToast(`Sorted: ${filename} → ${destination}`);
      await loadAll();
    } else {
      showToast(data.error || "Sort failed", "error");
    }
  } catch (err) {
    showToast(`Error: ${err}`, "error");
  }
}

async function resolveTriageDirect(filename, destination) {
  if (!destination || destination === "Requires Triage") {
    openDestPickerForFile(filename);
    return;
  }
  await singleSort(filename, destination);
}

async function undoLastMove() {
  try {
    const res = await fetch("/api/undo", { method: "POST" });
    const data = await res.json();
    if (data.success) {
      showToast(`Undone: Restored ${data.file} back to main folder.`);
      await loadAll();
    } else {
      showToast(data.error || "Nothing to undo", "error");
    }
  } catch (err) {
    showToast(`Error: ${err}`, "error");
  }
}

/* Modal Management */
function openCreateFolderModal() {
  document.getElementById("modalTitle").innerText = "Create New Course";
  document.getElementById("newFolderPath").value = "";
  document.getElementById("newFolderPath").placeholder = "e.g. Jurisprudence";
  document.getElementById("createFolderModal").classList.remove("hidden");
  document.getElementById("newFolderPath").focus();
}

function openCreateSubfolderModal(parentCourse) {
  document.getElementById("modalTitle").innerText = `Add Topic to ${parentCourse}`;
  document.getElementById("newFolderPath").value = `${parentCourse}/`;
  document.getElementById("newFolderPath").placeholder = "e.g. Seminar 1 - Positivism";
  document.getElementById("createFolderModal").classList.remove("hidden");
  document.getElementById("newFolderPath").focus();
}

function closeCreateFolderModal() {
  document.getElementById("createFolderModal").classList.add("hidden");
}

async function submitCreateFolder() {
  const path = document.getElementById("newFolderPath").value.trim();
  if (!path) return;

  try {
    const res = await fetch("/api/folders/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path })
    });
    const data = await res.json();
    if (data.created) {
      showToast(`Created folder: ${data.relative_path}`);
      closeCreateFolderModal();
      await loadTaxonomy();
    } else {
      showToast(data.error || "Failed to create folder", "error");
    }
  } catch (err) {
    showToast(`Error: ${err}`, "error");
  }
}

function scrollToTriage() {
  const section = document.getElementById("triageSection");
  section.classList.remove("hidden");
  section.scrollIntoView({ behavior: "smooth" });
}

function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  const toast = document.createElement("div");
  toast.className = "toast";
  if (type === "error") {
    toast.style.background = "#e11d48";
  }
  toast.innerText = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeJsString(str) {
  if (!str) return "";
  return String(str).replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

async function exitApp() {
  try {
    await fetch("/api/shutdown", { method: "POST" });
  } catch (e) {}
  window.close();
}

async function checkUpdate() {
  try {
    const res = await fetch("/api/check_update");
    if (!res.ok) return;
    const data = await res.json();
    const pill = document.getElementById("updatePill");
    const label = document.getElementById("updatePillText");
    if (!pill || !label) return;
    if (data && data.has_update && data.latest_version) {
      const version = String(data.latest_version).replace(/^v/i, "");
      label.textContent = `Update v${version} available`;
      pill.classList.remove("hidden");
      pill.dataset.url = data.release_url || "";
    } else {
      pill.classList.add("hidden");
    }
  } catch (err) {
    // Update checks are best-effort; never interrupt sorting.
  }
}

async function openRelease() {
  try {
    await fetch("/api/open_release", { method: "POST" });
  } catch (err) {
    const pill = document.getElementById("updatePill");
    const url = pill && pill.dataset.url;
    if (url) window.open(url, "_blank", "noopener");
  }
}
