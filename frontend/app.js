(() => {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");
  const selectedFileEl = document.getElementById("selected-file");
  const selectedFileName = document.getElementById("selected-file-name");
  const clearFileBtn = document.getElementById("clear-file-btn");
  const uploadError = document.getElementById("upload-error");
  const startBtn = document.getElementById("start-btn");

  const uploadCard = document.getElementById("upload-card");
  const progressCard = document.getElementById("progress-card");
  const doneCard = document.getElementById("done-card");

  const progressBarFill = document.getElementById("progress-bar-fill");
  const progressCaption = document.getElementById("progress-caption");
  const itemList = document.getElementById("item-list");
  const stopBtn = document.getElementById("stop-btn");
  const progressTitle = document.getElementById("progress-title");

  const doneIcon = document.getElementById("done-icon");
  const doneTitle = document.getElementById("done-title");
  const doneSubtitle = document.getElementById("done-subtitle");
  const summaryRow = document.getElementById("summary-row");
  const downloadBtn = document.getElementById("download-btn");
  const downloadFailuresBtn = document.getElementById("download-failures-btn");
  const restartBtn = document.getElementById("restart-btn");

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
      showUploadError("That's not a .xlsx file. Export your sheet from Matrixify as Excel first.");
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
    form.append("domain", val("opt-domain"));
    form.append("asin_column", val("opt-asin-column"));
    form.append("sheet", val("opt-sheet"));
    form.append("limit", val("opt-limit"));
    form.append("min_delay", val("opt-min-delay"));
    form.append("max_delay", val("opt-max-delay"));
    if (document.getElementById("opt-headed").checked) form.append("headed", "on");
    if (document.getElementById("opt-fresh-session").checked) form.append("fresh_session", "on");

    try {
      const res = await fetch("/api/jobs", { method: "POST", body: form });
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
    startBtn.textContent = "Start";
  }

  // -- progress ----------------------------------------------------------

  function showProgressCard(total) {
    uploadCard.hidden = true;
    doneCard.hidden = true;
    progressCard.hidden = false;
    progressTitle.textContent = "Processing your products…";
    progressCaption.textContent = `0 of ${total} processed`;
    progressBarFill.style.width = "0%";
    itemList.innerHTML = "";
    stopBtn.disabled = false;
    stopBtn.textContent = "Stop";
  }

  stopBtn.addEventListener("click", async () => {
    if (!currentJobId) return;
    stopBtn.disabled = true;
    stopBtn.textContent = "Stopping…";
    await fetch(`/api/jobs/${currentJobId}/stop`, { method: "POST" });
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
      const res = await fetch(`/api/jobs/${currentJobId}`);
      data = await res.json();
    } catch (err) {
      return; // transient network hiccup, try again next tick
    }
    if (!data || data.error === "Unknown job") return;

    const pct = data.total ? Math.round((data.current / data.total) * 100) : 0;
    progressBarFill.style.width = `${pct}%`;
    progressCaption.textContent = `${data.current} of ${data.total} processed`;
    renderItems(data.items);

    if (data.done) {
      clearInterval(pollTimer);
      showDone(data);
    }
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
      meta.textContent = item.status === "ok" ? `${item.image_count} image${item.image_count === 1 ? "" : "s"}` : "";

      li.append(badge, asin, title, meta);
      itemList.appendChild(li);
    }
  }

  // -- done ----------------------------------------------------------------

  function showDone(data) {
    progressCard.hidden = true;
    doneCard.hidden = false;

    const okCount = data.items.filter((i) => i.status === "ok").length;
    const failCount = data.items.length - okCount;

    if (data.error) {
      doneIcon.textContent = "!";
      doneIcon.className = "done-icon has-failures";
      doneTitle.textContent = "Run stopped early";
      doneSubtitle.textContent = data.error;
    } else if (failCount === 0) {
      doneIcon.textContent = "✓";
      doneIcon.className = "done-icon";
      doneTitle.textContent = "All done";
      doneSubtitle.textContent = `All ${okCount} product${okCount === 1 ? "" : "s"} scraped successfully.`;
    } else {
      doneIcon.textContent = "!";
      doneIcon.className = "done-icon has-failures";
      doneTitle.textContent = "Done, with a few that need attention";
      doneSubtitle.textContent = `${failCount} product${failCount === 1 ? "" : "s"} couldn't be scraped — their rows are left blank, see the failures log.`;
    }

    summaryRow.innerHTML = "";
    summaryRow.appendChild(summaryPill(okCount, "Succeeded"));
    summaryRow.appendChild(summaryPill(failCount, "Failed"));

    downloadBtn.href = `/api/jobs/${currentJobId}/download`;
    if (data.has_failures) {
      downloadFailuresBtn.hidden = false;
      downloadFailuresBtn.onclick = () => {
        window.location = `/api/jobs/${currentJobId}/failures`;
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
