(() => {
  const mainContent = document.getElementById("main-content");
  const sidebar = document.getElementById("sidebar");
  const sidebarBackdrop = document.getElementById("sidebar-backdrop");
  const mobileMenuBtn = document.getElementById("mobile-menu-btn");
  const syncSoldBtn = document.getElementById("sync-sold-btn");
  const syncNote = document.getElementById("sync-note");

  // -- tiny router ----------------------------------------------------------

  function navigate(path, { replace = false } = {}) {
    if (replace) history.replaceState(null, "", path);
    else history.pushState(null, "", path);
    render();
  }

  document.addEventListener("click", (e) => {
    const link = e.target.closest("[data-link]");
    if (!link) return;
    e.preventDefault();
    closeSidebar();
    navigate(link.getAttribute("href"));
  });
  window.addEventListener("popstate", render);

  // -- mobile sidebar ---------------------------------------------------------

  function openSidebar() {
    sidebar.classList.add("open");
    sidebarBackdrop.hidden = false;
  }
  function closeSidebar() {
    sidebar.classList.remove("open");
    sidebarBackdrop.hidden = true;
  }
  mobileMenuBtn.addEventListener("click", openSidebar);
  sidebarBackdrop.addEventListener("click", closeSidebar);

  // -- sidebar sync button ----------------------------------------------------

  syncSoldBtn.addEventListener("click", async () => {
    syncSoldBtn.disabled = true;
    syncSoldBtn.textContent = "Checking...";
    syncNote.textContent = "";
    try {
      const res = await fetch("/api/inventory/sync-sold", { method: "POST" });
      const result = await res.json();
      syncNote.textContent = res.ok
        ? `${result.newly_sold} item${result.newly_sold === 1 ? "" : "s"} marked sold.`
        : result.error || "Sync failed.";
      if (res.ok && location.pathname.includes("/products") && !location.pathname.match(/\/\d+/)) {
        render();
      }
    } catch (err) {
      syncNote.textContent = "Couldn't reach the server.";
    } finally {
      syncSoldBtn.disabled = false;
      syncSoldBtn.textContent = "Sync sold status";
    }
  });

  function setActiveNav(status) {
    document.querySelectorAll(".nav-link").forEach((a) => {
      a.classList.toggle("active", a.dataset.status === (status || ""));
    });
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  // -- api helpers --------------------------------------------------------

  async function apiGet(url) {
    const res = await fetch(url);
    return { ok: res.ok, data: await res.json() };
  }
  async function apiJson(url, method, body) {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return { ok: res.ok, data: await res.json() };
  }

  // ====================================================================
  // LIST PAGE
  // ====================================================================

  async function renderListPage(status) {
    setActiveNav(status);
    mainContent.innerHTML = `
      <div class="page-header"><h1>Products</h1></div>
      <div class="search-row"><input type="search" id="search-input" placeholder="Search by SKU, LPN, ASIN or title..." /></div>
      <div id="list-body"></div>
    `;
    const searchInput = document.getElementById("search-input");
    const listBody = document.getElementById("list-body");

    let timer = null;
    const load = async () => {
      const params = new URLSearchParams();
      if (searchInput.value.trim()) params.set("q", searchInput.value.trim());
      if (status) params.set("status", status);
      const { data } = await apiGet(`/api/inventory/products?${params}`);
      renderProductTable(listBody, data.products || []);
    };
    searchInput.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(load, 300);
    });
    load();
  }

  function renderProductTable(container, products) {
    if (!products.length) {
      container.innerHTML = `<p class="empty-text">No items found.</p>`;
      return;
    }
    const rows = products
      .map((p) => {
        const thumb = p.images && p.images[0] ? p.images[0].url : "";
        const shopifyUrl = shopifyProductUrl(p);
        return `
        <tr class="product-row" data-id="${p.id}">
          <td>${thumb ? `<img class="product-thumb" src="${thumb}" />` : `<div class="product-thumb"></div>`}</td>
          <td>
            <div class="product-title-cell">${escapeHtml(p.title || p.lpn || "(untitled)")}</div>
            <div class="product-meta-cell">${escapeHtml([p.sku, p.asin].filter(Boolean).join(" · "))}</div>
          </td>
          <td class="product-meta-cell">${escapeHtml(p.lpn || "")}</td>
          <td><span class="badge badge-${p.status}">${p.status}</span></td>
          <td class="product-meta-cell">${p.price ? "£" + escapeHtml(p.price) : ""}</td>
          <td class="menu-cell">
            <button type="button" class="row-menu-btn" data-menu-id="${p.id}">&#8942;</button>
            <div class="row-menu" id="row-menu-${p.id}" hidden>
              <a href="/inventory/products/${p.id}/edit" data-link>Edit</a>
              ${shopifyUrl ? `<a href="${shopifyUrl}" target="_blank" rel="noopener">View in Shopify</a>` : ""}
              ${p.status !== "archived" ? `<button type="button" data-action="archive" data-id="${p.id}">Archive</button>` : `<button type="button" data-action="draft" data-id="${p.id}">Move to Draft</button>`}
            </div>
          </td>
        </tr>`;
      })
      .join("");
    container.innerHTML = `
      <table class="product-table">
        <thead><tr><th></th><th>Product</th><th>LPN</th><th>Status</th><th>Price</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    container.querySelectorAll(".product-row").forEach((row) => {
      row.addEventListener("click", (e) => {
        if (e.target.closest(".menu-cell")) return;
        navigate(`/inventory/products/${row.dataset.id}`);
      });
    });
    wireRowMenus(container);
  }

  function shopifyProductUrl(p) {
    if (!p.shopify_product_id || !p.shop_domain) return "";
    const numericId = p.shopify_product_id.split("/").pop();
    return `https://${p.shop_domain}/admin/products/${numericId}`;
  }

  function wireRowMenus(container) {
    container.querySelectorAll(".row-menu-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const menu = document.getElementById(`row-menu-${btn.dataset.menuId}`);
        const wasOpen = !menu.hidden;
        container.querySelectorAll(".row-menu").forEach((m) => (m.hidden = true));
        menu.hidden = wasOpen;
      });
    });
    container.querySelectorAll(".row-menu [data-action]").forEach((actionBtn) => {
      actionBtn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const id = actionBtn.dataset.id;
        const status = actionBtn.dataset.action === "archive" ? "archived" : "draft";
        await apiJson(`/api/inventory/products/${id}/status`, "POST", { status });
        render();
      });
    });
    document.addEventListener(
      "click",
      () => container.querySelectorAll(".row-menu").forEach((m) => (m.hidden = true)),
      { once: true }
    );
  }

  // ====================================================================
  // VIEW PAGE
  // ====================================================================

  async function renderViewPage(id) {
    setActiveNav(null);
    mainContent.innerHTML = `<p class="empty-text">Loading...</p>`;
    const { ok, data: product } = await apiGet(`/api/inventory/products/${id}`);
    if (!ok) {
      mainContent.innerHTML = `<p class="empty-text">Item not found.</p>`;
      return;
    }

    const photos = (product.images || [])
      .map((img) => `<img src="${img.url}" />`)
      .join("");

    const detail = (label, value) => `
      <div class="detail-item">
        <div class="detail-label">${label}</div>
        <div class="detail-value">${value ? escapeHtml(value) : "—"}</div>
      </div>`;

    mainContent.innerHTML = `
      <button class="btn btn-ghost" id="back-btn" style="margin-bottom:14px;">&larr; Back to products</button>
      <div class="view-card">
        <div class="view-top">
          <div>
            <h1 class="view-title">${escapeHtml(product.title || product.lpn || "(untitled)")}</h1>
            <span class="badge badge-${product.status}">${product.status}</span>
          </div>
          <div class="view-actions">
            <a class="btn btn-secondary" href="/inventory/products/${id}/edit" data-link>Edit</a>
            <button class="btn btn-primary" id="list-btn">List on Shopify</button>
          </div>
        </div>

        ${photos ? `<div class="photo-gallery">${photos}</div>` : ""}

        <div class="detail-grid">
          ${detail("LPN", product.lpn)}
          ${detail("SKU", product.sku)}
          ${detail("ASIN", product.asin)}
          ${detail("Condition", product.condition)}
          ${detail("UPC", product.upc)}
          ${detail("EAN", product.ean)}
          ${detail("Price", product.price ? "£" + product.price : "")}
          ${detail("Weight (kg)", product.weight)}
          ${detail("Category", product.category)}
          <div class="detail-item detail-full">
            <div class="detail-label">Description</div>
            <div class="detail-value detail-description">${product.description ? escapeHtml(product.description) : "—"}</div>
          </div>
        </div>

        <p class="error-text" id="view-error" hidden></p>
        <p class="status-line" id="view-status"></p>
      </div>
    `;

    document.getElementById("back-btn").addEventListener("click", () => navigate("/inventory/products"));

    const listBtn = document.getElementById("list-btn");
    const viewError = document.getElementById("view-error");
    const viewStatus = document.getElementById("view-status");

    if (!product.asin) {
      listBtn.disabled = true;
      listBtn.title = "Add an ASIN first (via Edit)";
    }
    if (product.shopify_product_id) {
      listBtn.textContent = "Re-list / update on Shopify";
    }

    listBtn.addEventListener("click", async () => {
      viewError.hidden = true;
      listBtn.disabled = true;
      listBtn.textContent = "Listing on Shopify...";
      viewStatus.textContent = "Scraping Amazon and pushing to Shopify -- this can take 10-20 seconds...";
      try {
        const res = await fetch(`/api/inventory/products/${id}/list`, { method: "POST" });
        const result = await res.json();
        if (!res.ok) {
          viewError.textContent = result.error || "Listing failed.";
          viewError.hidden = false;
          return;
        }
        viewStatus.innerHTML = `Done (${result.status}). <a href="${result.shop_admin_url}" target="_blank" rel="noopener">View in Shopify</a>`;
      } catch (err) {
        viewError.textContent = "Couldn't reach the server.";
        viewError.hidden = false;
      } finally {
        listBtn.disabled = false;
        listBtn.textContent = "Re-list / update on Shopify";
      }
    });
  }

  // ====================================================================
  // FORM PAGE (new / edit)
  // ====================================================================

  async function renderFormPage(id) {
    setActiveNav(null);
    const isNew = !id;
    let product = {};
    if (!isNew) {
      mainContent.innerHTML = `<p class="empty-text">Loading...</p>`;
      const { ok, data } = await apiGet(`/api/inventory/products/${id}`);
      if (!ok) {
        mainContent.innerHTML = `<p class="empty-text">Item not found.</p>`;
        return;
      }
      product = data;
    }

    mainContent.innerHTML = `
      <button class="btn btn-ghost" id="back-btn" style="margin-bottom:14px;">&larr; ${isNew ? "Cancel" : "Back to item"}</button>
      <div class="form-card">
        <div class="field-row">
          <label class="field">LPN *<input type="text" id="f-lpn" /></label>
          <label class="field">SKU<input type="text" id="f-sku" /></label>
        </div>
        <div class="field-row">
          <label class="field">ASIN<input type="text" id="f-asin" /></label>
          <label class="field">Condition<input type="text" id="f-condition" /></label>
        </div>
        <div class="field-row">
          <label class="field">UPC<input type="text" id="f-upc" /></label>
          <label class="field">EAN<input type="text" id="f-ean" /></label>
        </div>
        <div class="field-row">
          <label class="field">Price<input type="text" id="f-price" inputmode="decimal" /></label>
          <label class="field">Weight (kg)<input type="text" id="f-weight" inputmode="decimal" /></label>
        </div>
        <label class="field full">Category<input type="text" id="f-category" /></label>
        <label class="field full">Title<input type="text" id="f-title" placeholder="Leave blank to use Amazon's title" /></label>
        <label class="field full">Description<textarea id="f-description" rows="4" placeholder="Leave blank to use Amazon's description"></textarea></label>

        <div class="photos-block">
          <p class="block-label">Photos</p>
          <div class="photo-grid" id="photo-grid"></div>
          ${
            isNew
              ? `<p class="status-line">Save the item first, then you can add photos.</p>`
              : `<label class="btn btn-secondary photo-add-btn">+ Add photo<input type="file" id="photo-input" accept="image/*" capture="environment" multiple hidden /></label>`
          }
        </div>

        <p class="error-text" id="form-error" hidden></p>
        <p class="status-line" id="status-line"></p>

        <div class="form-actions">
          <button class="btn btn-primary" id="save-btn">Save</button>
        </div>
      </div>
    `;

    document.getElementById("back-btn").addEventListener("click", () => {
      navigate(isNew ? "/inventory/products" : `/inventory/products/${id}`);
    });

    fillForm(product);
    if (!isNew) wirePhotoUpload(id);

    document.getElementById("save-btn").addEventListener("click", () => saveForm(isNew ? null : id));
  }

  function fillForm(product) {
    const set = (elId, val) => (document.getElementById(elId).value = val || "");
    set("f-lpn", product.lpn);
    set("f-sku", product.sku);
    set("f-asin", product.asin);
    set("f-condition", product.condition);
    set("f-upc", product.upc);
    set("f-ean", product.ean);
    set("f-price", product.price);
    set("f-weight", product.weight);
    set("f-category", product.category);
    set("f-title", product.title);
    set("f-description", product.description);
    renderPhotoGrid(product.images || [], product.id);
    const statusLine = document.getElementById("status-line");
    if (product.id) statusLine.textContent = `Status: ${product.status}`;
  }

  function renderPhotoGrid(images, productId) {
    const grid = document.getElementById("photo-grid");
    grid.innerHTML = images
      .map(
        (img) => `
      <div class="photo-thumb" data-image-id="${img.id}">
        <img src="${img.url}" />
        <button type="button" class="photo-remove">&times;</button>
      </div>`
      )
      .join("");
    grid.querySelectorAll(".photo-remove").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const thumb = e.target.closest(".photo-thumb");
        await fetch(`/api/inventory/images/${thumb.dataset.imageId}`, { method: "DELETE" });
        const { data } = await apiGet(`/api/inventory/products/${productId}`);
        renderPhotoGrid(data.images || [], productId);
      });
    });
  }

  function wirePhotoUpload(id) {
    const input = document.getElementById("photo-input");
    if (!input) return;
    input.addEventListener("change", async () => {
      for (const file of input.files) {
        const form = new FormData();
        form.append("file", file);
        try {
          await fetch(`/api/inventory/products/${id}/images`, { method: "POST", body: form });
        } catch (err) {
          /* best-effort per file */
        }
      }
      input.value = "";
      const { data } = await apiGet(`/api/inventory/products/${id}`);
      renderPhotoGrid(data.images || [], id);
    });
  }

  function collectForm() {
    const get = (elId) => document.getElementById(elId).value.trim();
    return {
      lpn: get("f-lpn"),
      sku: get("f-sku"),
      asin: get("f-asin").toUpperCase(),
      condition: get("f-condition"),
      upc: get("f-upc"),
      ean: get("f-ean"),
      price: get("f-price"),
      weight: get("f-weight"),
      category: get("f-category"),
      title: get("f-title"),
      description: get("f-description"),
    };
  }

  async function saveForm(id) {
    const formError = document.getElementById("form-error");
    const saveBtn = document.getElementById("save-btn");
    const data = collectForm();
    formError.hidden = true;
    if (!data.lpn) {
      formError.textContent = "LPN is required.";
      formError.hidden = false;
      return;
    }
    saveBtn.disabled = true;
    saveBtn.textContent = "Saving...";
    try {
      const { ok, data: result } = id
        ? await apiJson(`/api/inventory/products/${id}`, "PUT", data)
        : await apiJson("/api/inventory/products", "POST", data);
      if (!ok) {
        formError.textContent = result.error || "Could not save.";
        formError.hidden = false;
        return;
      }
      navigate(id ? `/inventory/products/${id}` : `/inventory/products/${result.id}/edit`, { replace: !id });
    } catch (err) {
      formError.textContent = "Couldn't reach the server.";
      formError.hidden = false;
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "Save";
    }
  }

  // ====================================================================
  // ROUTER
  // ====================================================================

  function render() {
    closeSidebar();
    const path = location.pathname;
    const params = new URLSearchParams(location.search);

    let m;
    if ((m = path.match(/^\/inventory\/products\/new\/?$/))) {
      renderFormPage(null);
    } else if ((m = path.match(/^\/inventory\/products\/(\d+)\/edit\/?$/))) {
      renderFormPage(m[1]);
    } else if ((m = path.match(/^\/inventory\/products\/(\d+)\/?$/))) {
      renderViewPage(m[1]);
    } else {
      renderListPage(params.get("status") || "");
    }
  }

  render();
})();
