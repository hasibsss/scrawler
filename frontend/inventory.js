(() => {
  const listView = document.getElementById("list-view");
  const detailView = document.getElementById("detail-view");
  const newBtn = document.getElementById("new-btn");
  const backBtn = document.getElementById("back-btn");

  const searchInput = document.getElementById("search-input");
  const statusFilter = document.getElementById("status-filter");
  const productList = document.getElementById("product-list");
  const emptyText = document.getElementById("empty-text");
  const syncSoldBtn = document.getElementById("sync-sold-btn");
  const syncNote = document.getElementById("sync-note");

  const fields = {
    lpn: document.getElementById("f-lpn"),
    sku: document.getElementById("f-sku"),
    asin: document.getElementById("f-asin"),
    condition: document.getElementById("f-condition"),
    upc: document.getElementById("f-upc"),
    ean: document.getElementById("f-ean"),
    price: document.getElementById("f-price"),
    weight: document.getElementById("f-weight"),
    category: document.getElementById("f-category"),
    title: document.getElementById("f-title"),
    description: document.getElementById("f-description"),
  };

  const photoGrid = document.getElementById("photo-grid");
  const photoInput = document.getElementById("photo-input");
  const formError = document.getElementById("form-error");
  const statusLine = document.getElementById("status-line");
  const saveBtn = document.getElementById("save-btn");
  const listBtn = document.getElementById("list-btn");

  let current = null; // null = new/unsaved, else the loaded product object
  let searchTimer = null;

  // -- list view -----------------------------------------------------------

  async function loadList() {
    const q = searchInput.value.trim();
    const status = statusFilter.value;
    const params = new URLSearchParams();
    if (q) params.set("q", q);
    if (status) params.set("status", status);
    let data;
    try {
      const res = await fetch(`/api/inventory/products?${params}`);
      data = await res.json();
    } catch (err) {
      return;
    }
    renderList(data.products || []);
  }

  function renderList(products) {
    productList.innerHTML = "";
    emptyText.hidden = products.length > 0;
    for (const p of products) {
      const li = document.createElement("li");
      li.className = "product-card";
      li.addEventListener("click", () => openDetail(p));

      const thumbSrc = p.images && p.images[0] ? p.images[0].url : "";
      const thumb = document.createElement("img");
      thumb.className = "product-thumb";
      thumb.src = thumbSrc;
      thumb.style.visibility = thumbSrc ? "visible" : "hidden";

      const info = document.createElement("div");
      info.className = "product-info";
      const title = document.createElement("div");
      title.className = "product-title";
      title.textContent = p.title || p.lpn || "(untitled)";
      const meta = document.createElement("div");
      meta.className = "product-meta";
      meta.textContent = [p.lpn, p.sku, p.asin].filter(Boolean).join(" · ");
      info.append(title, meta);

      const badge = document.createElement("span");
      badge.className = `badge badge-${p.status}`;
      badge.textContent = p.status;

      li.append(thumb, info, badge);
      productList.appendChild(li);
    }
  }

  searchInput.addEventListener("input", () => {
    clearInterval(searchTimer);
    searchTimer = setTimeout(loadList, 300);
  });
  statusFilter.addEventListener("change", loadList);

  syncSoldBtn.addEventListener("click", async () => {
    syncSoldBtn.disabled = true;
    syncSoldBtn.textContent = "Checking Shopify...";
    syncNote.textContent = "";
    try {
      const res = await fetch("/api/inventory/sync-sold", { method: "POST" });
      const result = await res.json();
      syncNote.textContent = res.ok
        ? `${result.newly_sold} item${result.newly_sold === 1 ? "" : "s"} marked sold.`
        : result.error || "Sync failed.";
      if (res.ok) loadList();
    } catch (err) {
      syncNote.textContent = "Couldn't reach the server.";
    } finally {
      syncSoldBtn.disabled = false;
      syncSoldBtn.textContent = "Sync sold status";
    }
  });

  // -- detail/edit view -----------------------------------------------------

  function showList() {
    detailView.hidden = true;
    listView.hidden = false;
    loadList();
  }

  function showDetail() {
    listView.hidden = true;
    detailView.hidden = false;
  }

  function clearForm() {
    for (const el of Object.values(fields)) el.value = "";
    photoGrid.innerHTML = "";
    formError.hidden = true;
    statusLine.textContent = "";
  }

  function fillForm(product) {
    fields.lpn.value = product.lpn || "";
    fields.sku.value = product.sku || "";
    fields.asin.value = product.asin || "";
    fields.condition.value = product.condition || "";
    fields.upc.value = product.upc || "";
    fields.ean.value = product.ean || "";
    fields.price.value = product.price || "";
    fields.weight.value = product.weight || "";
    fields.category.value = product.category || "";
    fields.title.value = product.title || "";
    fields.description.value = product.description || "";
    renderPhotos(product.images || []);
    statusLine.textContent = `Status: ${product.status}${product.shopify_product_id ? " · listed on Shopify" : ""}`;
  }

  function renderPhotos(images) {
    photoGrid.innerHTML = "";
    for (const img of images) {
      const div = document.createElement("div");
      div.className = "photo-thumb";
      const el = document.createElement("img");
      el.src = img.url;
      const removeBtn = document.createElement("button");
      removeBtn.className = "photo-remove";
      removeBtn.textContent = "×";
      removeBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        await fetch(`/api/inventory/images/${img.id}`, { method: "DELETE" });
        current = await (await fetch(`/api/inventory/products/${current.id}`)).json();
        renderPhotos(current.images || []);
      });
      div.append(el, removeBtn);
      photoGrid.appendChild(div);
    }
  }

  function openDetail(product) {
    current = product;
    clearForm();
    fillForm(product);
    showDetail();
  }

  newBtn.addEventListener("click", () => {
    current = null;
    clearForm();
    statusLine.textContent = "Not saved yet -- fill in at least an LPN and press Save.";
    showDetail();
  });

  backBtn.addEventListener("click", showList);

  function collectForm() {
    return {
      lpn: fields.lpn.value.trim(),
      sku: fields.sku.value.trim(),
      asin: fields.asin.value.trim().toUpperCase(),
      condition: fields.condition.value.trim(),
      upc: fields.upc.value.trim(),
      ean: fields.ean.value.trim(),
      price: fields.price.value.trim(),
      weight: fields.weight.value.trim(),
      category: fields.category.value.trim(),
      title: fields.title.value.trim(),
      description: fields.description.value.trim(),
    };
  }

  function showError(message) {
    formError.textContent = message;
    formError.hidden = false;
  }

  saveBtn.addEventListener("click", async () => {
    formError.hidden = true;
    const data = collectForm();
    if (!data.lpn) {
      showError("LPN is required.");
      return;
    }
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
    try {
      const isNew = !current || !current.id;
      const url = isNew ? "/api/inventory/products" : `/api/inventory/products/${current.id}`;
      const res = await fetch(url, {
        method: isNew ? "POST" : "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      const result = await res.json();
      if (!res.ok) {
        showError(result.error || "Could not save.");
        return;
      }
      current = result;
      fillForm(current);
      statusLine.textContent = `Saved. Status: ${current.status}`;
    } catch (err) {
      showError("Couldn't reach the server.");
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
    }
  });

  photoInput.addEventListener("change", async () => {
    if (!current || !current.id) {
      showError("Save the item first, then add photos.");
      photoInput.value = "";
      return;
    }
    for (const file of photoInput.files) {
      const form = new FormData();
      form.append("file", file);
      try {
        await fetch(`/api/inventory/products/${current.id}/images`, { method: "POST", body: form });
      } catch (err) {
        showError("A photo failed to upload.");
      }
    }
    photoInput.value = "";
    current = await (await fetch(`/api/inventory/products/${current.id}`)).json();
    renderPhotos(current.images || []);
  });

  listBtn.addEventListener("click", async () => {
    if (!current || !current.id) {
      showError("Save the item first.");
      return;
    }
    if (!current.asin) {
      showError("Add an ASIN before listing on Shopify.");
      return;
    }
    formError.hidden = true;
    listBtn.disabled = true;
    listBtn.textContent = "Listing on Shopify...";
    statusLine.textContent = "Scraping Amazon and pushing to Shopify -- this can take 10-20 seconds...";
    try {
      const res = await fetch(`/api/inventory/products/${current.id}/list`, { method: "POST" });
      const result = await res.json();
      if (!res.ok) {
        showError(result.error || "Listing failed.");
        return;
      }
      current = await (await fetch(`/api/inventory/products/${current.id}`)).json();
      statusLine.innerHTML = `Done (${result.status}). <a href="${result.shop_admin_url}" target="_blank" rel="noopener">View in Shopify</a>`;
    } catch (err) {
      showError("Couldn't reach the server.");
    } finally {
      listBtn.disabled = false;
      listBtn.textContent = "List on Shopify";
    }
  });

  loadList();
})();
