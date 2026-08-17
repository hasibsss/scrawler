(() => {
  const dropzone = document.getElementById("direct-dropzone");
  const fileInput = document.getElementById("direct-file-input");
  const selectedFileEl = document.getElementById("direct-selected-file");
  const selectedFileName = document.getElementById("direct-selected-file-name");
  const clearFileBtn = document.getElementById("direct-clear-file-btn");
  const uploadError = document.getElementById("direct-upload-error");
  const startBtn = document.getElementById("direct-start-btn");

  const uploadCard = document.getElementById("direct-upload-card");
  const progressCard = document.getElementById("direct-progress-card");
  const doneCard = document.getElementById("direct-done-card");

  const progressBarFill = document.getElementById("direct-progress-bar-fill");
  const progressCaption = document.getElementById("direct-progress-caption");
  const liveStats = document.getElementById("direct-live-stats");
  const itemList = document.getElementById("direct-item-list");
  const stopBtn = document.getElementById("direct-stop-btn");
  const progressTitle = document.getElementById("direct-progress-title");

  const doneIcon = document.getElementById("direct-done-icon");
  const doneTitle = document.getElementById("direct-done-title");
  const doneSubtitle = document.getElementById("direct-done-subtitle");
  const summaryRow = document.getElementById("direct-summary-row");
  const viewStoreBtn = document.getElementById("direct-view-store-btn");
  const downloadFailuresBtn = document.getElementById("direct-download-failures-btn");
  const restartBtn = document.getElementById("direct-restart-btn");

  let selectedFile = null;
  let currentJobId = null;
  let pollTimer = null;

  // -- file selection --------------------------------------------------

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") fileInput.click();
  });

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) selectFile(file);
  });

  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) selectFile(fileInput.files[0]);
  });

  clearFileBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    selectedFile = null;
    fileInput.value = "";
    selectedFileEl.hidden = true;
    dropzone.hidden = false;
    startBtn.disabled = true;
  });

  function selectFile(file) {
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      showUploadError("That's not a .xlsx file.");
      return;
    }
    hideUploadError();
    selectedFile = file;
    selectedFileName.textContent = file.name;
    selectedFileEl.hidden = false;
    dropzone.hidden = true;
    startBtn.disabled = false;
  }

  function showUploadError(message) {
    uploadError.textContent = message;
    uploadError.hidden = false;
  }
  function hideUploadError() {
    uploadError.hidden = true;
  }

  // -- starting a run ----------------------------------------------------

  startBtn.addEventListener("click", async () => {
    if (!selectedFile) return;
    hideUploadError();
    startBtn.disabled = true;
    startBtn.textContent = "Starting...";

    const form = new FormData();
    form.append("file", selectedFile);
    form.append("domain", val("direct-opt-domain"));
    form.append("asin_column", val("direct-opt-asin-column"));
    form.append("lpn_column", val("direct-opt-lpn-column"));
    form.append("sheet", val("direct-opt-sheet"));
    form.append("limit", val("direct-opt-limit"));
    form.append("min_delay", val("direct-opt-min-delay"));
    form.append("max_delay", val("direct-opt-max-delay"));
    if (document.getElementById("direct-opt-headed").checked) form.append("headed", "on");

    try {
      const res = await fetch("/api/direct-jobs", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) {
        showUploadError(data.error || "Something went wrong starting the job.");
        resetStartButton();
        return;
      }
      currentJobId = data.job_id;
      showProgressCard(data.total);
      startPolling();
    } catch (err) {
      showUploadError("Couldn't reach the server. Is it still running?");
      resetStartButton();
    }
  });

  function val(id) {
    return document.getElementById(id).value.trim();
  }

  function resetStartButton() {
    startBtn.disabled = false;
    startBtn.textContent = "List on Shopify";
  }

  // -- progress ----------------------------------------------------------

  function showProgressCard(total) {
    uploadCard.hidden = true;
    doneCard.hidden = true;
    progressCard.hidden = false;
    progressTitle.textContent = "Listing your products on Shopify…";
    progressCaption.textContent = `0 of ${total} processed`;
    progressBarFill.style.width = "0%";
    itemList.innerHTML = "";
    renderLiveStats([]);
    stopBtn.disabled = false;
    stopBtn.textContent = "Stop";
  }

  stopBtn.addEventListener("click", async () => {
    if (!currentJobId) return;
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping…";
    await fetch(`/api/direct-jobs/${currentJobId}/stop`, { method: "POST" });
  });

  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(pollStatus, 1000);
    pollStatus();
  }

  async function pollStatus() {
    if (!currentJobId) return;
    let data;
    try {
      const res = await fetch(`/api/direct-jobs/${currentJobId}`);
      data = await res.json();
    } catch (err) {
      return; // transient network hiccup, try again next tick
    }
    if (!data || data.error === "Unknown job") return;

    const pct = data.total ? Math.round((data.current / data.total) * 100) : 0;
    progressBarFill.style.width = `${pct}%`;
    progressCaption.textContent = `${data.current} of ${data.total} processed`;
    renderLiveStats(data.items, data.total);
    renderItems(data.items);

    if (data.done) {
      clearInterval(pollTimer);
      showDone(data);
    }
  }

  function renderLiveStats(items, total) {
    const created = items.filter((i) => i.status === "created").length;
    const updated = items.filter((i) => i.status === "updated").length;
    const failed = items.length - created - updated;
    const remaining = typeof total === "number" ? Math.max(total - items.length, 0) : null;

    liveStats.innerHTML = "";
    liveStats.appendChild(statChip("created", "Created", created));
    liveStats.appendChild(statChip("updated", "Updated", updated));
    liveStats.appendChild(statChip("failed", "Failed", failed));
    if (remaining !== null) {
      liveStats.appendChild(statChip("remaining", "Remaining", remaining));
    }
  }

  function statChip(kind, label, num) {
    const span = document.createElement("span");
    span.className = `stat-chip stat-chip-${kind}`;
    span.innerHTML = `<span class="num">${num}</span> ${label}`;
    return span;
  }

  function renderItems(items) {
    itemList.innerHTML = "";
    for (const item of items.slice().reverse()) {
      const li = document.createElement("li");

      const badge = document.createElement("span");
      badge.className = `badge badge-${item.status}`;
      badge.textContent = item.status.replace("_", " ");

      const asin = document.createElement("span");
      asin.className = "item-asin";
      asin.textContent = item.asin;

      const title = document.createElement("span");
      title.className = "item-title";
      title.textContent = item.title || item.notes || "";

      const meta = document.createElement("span");
      meta.className = "item-meta";
      meta.textContent = item.lpn || "";

      li.append(badge, asin, title, meta);
      itemList.appendChild(li);
    }
  }

  // -- done ----------------------------------------------------------------

  function showDone(data) {
    progressCard.hidden = true;
    doneCard.hidden = false;

    const createdCount = data.items.filter((i) => i.status === "created").length;
    const updatedCount = data.items.filter((i) => i.status === "updated").length;
    const failCount = data.items.length - createdCount - updatedCount;

    if (data.error) {
      doneIcon.textContent = "!";
      doneIcon.className = "done-icon has-failures";
      doneTitle.textContent = "Run stopped early";
      doneSubtitle.textContent = data.error;
    } else if (failCount === 0) {
      doneIcon.textContent = "✓";
      doneIcon.className = "done-icon";
      doneTitle.textContent = "All done";
      doneSubtitle.textContent = `${createdCount} created, ${updatedCount} updated on Shopify.`;
    } else {
      doneIcon.textContent = "!";
      doneIcon.className = "done-icon has-failures";
      doneTitle.textContent = "Done, with a few that need attention";
      doneSubtitle.textContent = `${failCount} product${failCount === 1 ? "" : "s"} couldn't be listed — see the failures log.`;
    }

    summaryRow.innerHTML = "";
    summaryRow.appendChild(summaryPill(createdCount, "Created"));
    summaryRow.appendChild(summaryPill(updatedCount, "Updated"));
    summaryRow.appendChild(summaryPill(failCount, "Failed"));

    viewStoreBtn.href = data.shop_admin_url || "#";
    if (data.has_failures) {
      downloadFailuresBtn.hidden = false;
      downloadFailuresBtn.onclick = () => {
        window.location = `/api/direct-jobs/${currentJobId}/failures`;
      };
    } else {
      downloadFailuresBtn.hidden = true;
    }
  }

  function summaryPill(num, label) {
    const div = document.createElement("div");
    div.className = "summary-pill";
    div.innerHTML = `<span class="num">${num}</span><span class="label">${label}</span>`;
    return div;
  }

  restartBtn.addEventListener("click", () => {
    currentJobId = null;
    selectedFile = null;
    fileInput.value = "";
    selectedFileEl.hidden = true;
    dropzone.hidden = false;
    resetStartButton();
    startBtn.disabled = true;
    doneCard.hidden = true;
    uploadCard.hidden = false;
  });
})();
