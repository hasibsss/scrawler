(() => {
  const sheetUrlInput = document.getElementById("sheet-url");
  const sheetError = document.getElementById("sheet-error");
  const startBtn = document.getElementById("sheet-start-btn");

  const connectCard = document.getElementById("sheet-connect-card");
  const progressCard = document.getElementById("sheet-progress-card");
  const doneCard = document.getElementById("sheet-done-card");

  const progressBarFill = document.getElementById("sheet-progress-bar-fill");
  const progressCaption = document.getElementById("sheet-progress-caption");
  const liveStats = document.getElementById("sheet-live-stats");
  const itemList = document.getElementById("sheet-item-list");
  const stopBtn = document.getElementById("sheet-stop-btn");
  const progressTitle = document.getElementById("sheet-progress-title");

  const doneIcon = document.getElementById("sheet-done-icon");
  const doneTitle = document.getElementById("sheet-done-title");
  const doneSubtitle = document.getElementById("sheet-done-subtitle");
  const summaryRow = document.getElementById("sheet-summary-row");
  const viewStoreBtn = document.getElementById("sheet-view-store-btn");
  const restartBtn = document.getElementById("sheet-restart-btn");

  let currentJobId = null;
  let pollTimer = null;

  function val(id) {
    return document.getElementById(id).value.trim();
  }

  function showError(message) {
    sheetError.textContent = message;
    sheetError.hidden = false;
  }
  function hideError() {
    sheetError.hidden = true;
  }

  startBtn.addEventListener("click", async () => {
    const sheetUrl = sheetUrlInput.value.trim();
    if (!sheetUrl) {
      showError("Paste a Google Sheet link first.");
      return;
    }
    hideError();
    startBtn.disabled = true;
    startBtn.textContent = "Syncing...";

    const body = {
      sheet_url: sheetUrl,
      worksheet_name: val("sheet-opt-worksheet"),
      domain: val("sheet-opt-domain"),
      limit: val("sheet-opt-limit"),
      min_delay: val("sheet-opt-min-delay"),
      max_delay: val("sheet-opt-max-delay"),
      headed: document.getElementById("sheet-opt-headed").checked,
    };

    try {
      const res = await fetch("/api/sheet-jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Something went wrong starting the sync.");
        resetStartButton();
        return;
      }
      currentJobId = data.job_id;
      showProgressCard(data.total);
      startPolling();
    } catch (err) {
      showError("Couldn't reach the server. Is it still running?");
      resetStartButton();
    }
  });

  function resetStartButton() {
    startBtn.disabled = false;
    startBtn.textContent = "Sync from Google Sheet";
  }

  function showProgressCard(total) {
    connectCard.hidden = true;
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
    await fetch(`/api/sheet-jobs/${currentJobId}/stop`, { method: "POST" });
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
      const res = await fetch(`/api/sheet-jobs/${currentJobId}`);
      data = await res.json();
    } catch (err) {
      return;
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

  function showDone(data) {
    progressCard.hidden = true;
    doneCard.hidden = false;

    const createdCount = data.items.filter((i) => i.status === "created").length;
    const updatedCount = data.items.filter((i) => i.status === "updated").length;
    const failCount = data.items.length - createdCount - updatedCount;

    if (data.error) {
      doneIcon.textContent = "!";
      doneIcon.className = "done-icon has-failures";
      doneTitle.textContent = "Sync stopped early";
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
      doneSubtitle.textContent = `${failCount} product${failCount === 1 ? "" : "s"} couldn't be listed — check the Status column in the sheet.`;
    }

    summaryRow.innerHTML = "";
    summaryRow.appendChild(summaryPill(createdCount, "Created"));
    summaryRow.appendChild(summaryPill(updatedCount, "Updated"));
    summaryRow.appendChild(summaryPill(failCount, "Failed"));

    viewStoreBtn.href = data.shop_admin_url || "#";
  }

  function summaryPill(num, label) {
    const div = document.createElement("div");
    div.className = "summary-pill";
    div.innerHTML = `<span class="num">${num}</span><span class="label">${label}</span>`;
    return div;
  }

  restartBtn.addEventListener("click", () => {
    currentJobId = null;
    resetStartButton();
    doneCard.hidden = true;
    connectCard.hidden = false;
  });
})();
