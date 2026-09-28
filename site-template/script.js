(function () {
  const chart = document.getElementById("chart");
  const nodesContainer = document.getElementById("nodes");
  const legend = document.getElementById("legend");
  const thumbToggle = document.getElementById("thumbToggle");
  const panelEmpty = document.getElementById("panelEmpty");
  const panelContent = document.getElementById("panelContent");
  const panelClose = document.getElementById("panelClose");
  const panelImageWrap = document.getElementById("panelImageWrap");
  const panelImage = document.getElementById("panelImage");
  const panelTitle = document.getElementById("panelTitle");
  const panelCategory = document.getElementById("panelCategory");
  const panelCategorySwatch = document.getElementById("panelCategorySwatch");
  const panelCategoryName = document.getElementById("panelCategoryName");
  const panelTags = document.getElementById("panelTags");
  const panelDescription = document.getElementById("panelDescription");
  const panelLink = document.getElementById("panelLink");

  let selectedEl = null;
  let categoriesById = {};

  // map data range [-1, 1] to percentage position [0, 100]
  // small inset keeps points off the very edge of the chart
  function toPercent(v) {
    const inset = 8;
    return ((v + 1) / 2) * (100 - inset * 2) + inset;
  }

  function loadThumbPref() {
    try {
      const stored = localStorage.getItem("portfolioMap.showThumbs");
      return stored === null ? true : stored === "true";
    } catch (e) {
      return true;
    }
  }

  function saveThumbPref(value) {
    try {
      localStorage.setItem("portfolioMap.showThumbs", String(value));
    } catch (e) {
      // ignore — private browsing / blocked storage
    }
  }

  function applyThumbPref(value) {
    chart.classList.toggle("thumbnails-on", value);
  }

  function renderLegend(categories) {
    legend.innerHTML = "";
    if (!categories.length) {
      legend.hidden = true;
      return;
    }
    legend.hidden = false;

    const title = document.createElement("span");
    title.className = "legend__title";
    title.textContent = "Category";
    legend.appendChild(title);

    categories.forEach((cat) => {
      const row = document.createElement("span");
      row.className = "legend__item";
      const swatch = document.createElement("span");
      swatch.className = "legend__swatch";
      swatch.style.background = cat.color;
      const label = document.createElement("span");
      label.textContent = cat.name;
      row.appendChild(swatch);
      row.appendChild(label);
      legend.appendChild(row);
    });
  }

  function renderNodes(nodes) {
    nodesContainer.innerHTML = "";
    nodes.forEach((node) => {
      const el = document.createElement("div");
      el.className = "node";
      if (node.image) el.classList.add("node--has-image");

      const category = categoriesById[node.category];
      if (category) {
        el.style.setProperty("--node-color", category.color);
      }

      el.style.left = toPercent(node.x) + "%";
      // y=1 (high fidelity) should render near the top, so invert
      el.style.top = toPercent(-node.y) + "%";
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.setAttribute("aria-label", node.title);
      el.dataset.id = node.id;

      if (node.image) {
        const thumb = document.createElement("span");
        thumb.className = "node__thumb";
        thumb.style.backgroundImage = `url("${node.image}")`;
        el.appendChild(thumb);
      }

      const dot = document.createElement("span");
      dot.className = "node__dot";
      el.appendChild(dot);

      const label = document.createElement("span");
      label.className = "node__label";
      label.textContent = node.title;
      el.appendChild(label);

      el.addEventListener("click", () => selectNode(node, el));
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectNode(node, el);
        }
      });

      nodesContainer.appendChild(el);
    });
  }

  function selectNode(node, el) {
    if (selectedEl) selectedEl.classList.remove("is-selected");
    el.classList.add("is-selected");
    selectedEl = el;
    showPanel(node);
  }

  function showPanel(node) {
    panelEmpty.hidden = true;
    panelContent.hidden = false;

    if (node.image) {
      panelImage.src = node.image;
      panelImage.alt = node.title;
      panelImageWrap.hidden = false;
    } else {
      panelImageWrap.hidden = true;
    }

    panelTitle.textContent = node.title;

    const category = categoriesById[node.category];
    if (category) {
      panelCategorySwatch.style.background = category.color;
      panelCategoryName.textContent = category.name;
      panelCategory.hidden = false;
    } else {
      panelCategory.hidden = true;
    }

    panelTags.innerHTML = "";
    (node.tags || []).forEach((tag) => {
      const span = document.createElement("span");
      span.className = "panel__tag";
      span.textContent = tag;
      panelTags.appendChild(span);
    });

    panelDescription.textContent = node.description || "";

    if (node.link) {
      panelLink.href = node.link;
      panelLink.style.display = "inline-block";
    } else {
      panelLink.style.display = "none";
    }
  }

  function closePanel() {
    panelContent.hidden = true;
    panelEmpty.hidden = false;
    if (selectedEl) {
      selectedEl.classList.remove("is-selected");
      selectedEl = null;
    }
  }

  panelClose.addEventListener("click", closePanel);

  thumbToggle.checked = loadThumbPref();
  applyThumbPref(thumbToggle.checked);
  thumbToggle.addEventListener("change", () => {
    applyThumbPref(thumbToggle.checked);
    saveThumbPref(thumbToggle.checked);
  });

  Promise.all([
    fetch("data/nodes.json").then((res) => res.json()),
    fetch("data/categories.json").then((res) => res.json())
  ])
    .then(([nodes, categories]) => {
      categoriesById = {};
      categories.forEach((cat) => {
        categoriesById[cat.id] = cat;
      });
      renderLegend(categories);
      renderNodes(nodes);
    })
    .catch((err) => {
      nodesContainer.innerHTML =
        '<p style="padding:24px;color:var(--text-dim)">Couldn\'t load node data. Make sure the site is running through server.py, not opened as a file.</p>';
      console.error(err);
    });
})();
