// Pixiv 랭킹 플러그인 - 카테고리 레벨 풀페이지 UI 로직
//
// 주의: 코어가 이 풀페이지에 아이템 데이터를 정확히 어떤 방식으로 전달하는지
// (내장 JSON vs 별도 fetch 엔드포인트) 문서로 확인되지 않은 상태이므로,
// 아래 loadItems()는 여러 후보를 순서대로 시도합니다.
// 브라우저 콘솔에 "[pixiv_ranking]" 로그가 각 시도 결과를 남기니,
// 실패 시 콘솔을 확인해서 실제 데이터 소스를 찾는 데 활용하세요.

(function () {
  "use strict";

  const PLUGIN_ID = "pixiv_ranking";
  const LOG_PREFIX = "[pixiv_ranking]";

  const els = {
    root: document.getElementById("pixiv-ranking-root"),
    tabs: document.getElementById("pxr-tabs"),
    grid: document.getElementById("pxr-grid"),
    status: document.getElementById("pxr-status"),
  };

  function log(...args) {
    console.log(LOG_PREFIX, ...args);
  }

  function warn(...args) {
    console.warn(LOG_PREFIX, ...args);
  }

  function setStatus(message, mode) {
    if (!els.status) return;
    if (!message) {
      els.status.style.display = "none";
      els.status.textContent = "";
      return;
    }
    els.status.style.display = "block";
    els.status.className = "pxr-status" + (mode === "loading" ? " pxr-loading" : "");
    els.status.textContent = message;
  }

  // ---------------------------------------------------------------
  // 1) 데이터 소스 탐색 (여러 후보를 순서대로 시도)
  // ---------------------------------------------------------------

  function tryEmbeddedJsonScriptTag() {
    const candidates = [
      "pixiv_ranking-data",
      "pixiv-ranking-data",
      "dashboard-data-" + PLUGIN_ID,
      "plugin-data-" + PLUGIN_ID,
    ];
    for (const id of candidates) {
      const el = document.getElementById(id);
      if (el && el.textContent) {
        try {
          const parsed = JSON.parse(el.textContent);
          log("내장 <script type=application/json> 태그에서 데이터 발견:", id);
          return parsed;
        } catch (e) {
          warn("내장 JSON 파싱 실패:", id, e);
        }
      }
    }
    return null;
  }

  function tryGlobalVariables() {
    const candidates = [
      "__DASHBOARD_ITEMS__",
      "__PLUGIN_DASHBOARD_DATA__",
      "PIXIV_RANKING_DASHBOARD_DATA",
      "__PLUGIN_DATA__",
    ];
    for (const name of candidates) {
      if (window[name] !== undefined) {
        log("전역 변수에서 데이터 발견:", name);
        return window[name];
      }
    }
    // data-* 속성에 JSON이 있는 경우
    if (els.root && els.root.dataset && els.root.dataset.items) {
      try {
        log("root 엘리먼트 data-items 속성에서 데이터 발견");
        return JSON.parse(els.root.dataset.items);
      } catch (e) {
        warn("data-items 파싱 실패:", e);
      }
    }
    return null;
  }

  async function tryFetchEndpoints() {
    const candidateUrls = [
      `/api/plugins/${PLUGIN_ID}/dashboard-data`,
      `/api/plugins/${PLUGIN_ID}/dashboard_data`,
      `/plugins/${PLUGIN_ID}/dashboard-data`,
      `/plugin/${PLUGIN_ID}/dashboard-data`,
      `/dashboard/widget/${PLUGIN_ID}`,
      `/dashboard/widget/${PLUGIN_ID}/data`,
      `/api/dashboard/${PLUGIN_ID}`,
    ];

    for (const url of candidateUrls) {
      try {
        const res = await fetch(url, { credentials: "same-origin" });
        if (!res.ok) {
          log("fetch 실패 (status " + res.status + "):", url);
          continue;
        }
        const json = await res.json();
        log("fetch 성공:", url);
        return json;
      } catch (e) {
        log("fetch 에러:", url, e && e.message);
      }
    }
    return null;
  }

  function extractItemsArray(payload) {
    if (!payload) return null;
    if (Array.isArray(payload)) return payload;
    if (Array.isArray(payload.items)) return payload.items;
    if (payload.success && Array.isArray(payload.data)) return payload.data;
    if (payload.result && Array.isArray(payload.result.items)) return payload.result.items;
    return null;
  }

  async function loadItems() {
    setStatus("Pixiv 랭킹 데이터를 불러오는 중입니다...", "loading");

    let payload = tryEmbeddedJsonScriptTag();
    if (!payload) payload = tryGlobalVariables();
    if (!payload) payload = await tryFetchEndpoints();

    const items = extractItemsArray(payload);

    if (!items || items.length === 0) {
      warn("어떤 방식으로도 데이터를 찾지 못했습니다. 콘솔의 [pixiv_ranking] 로그를 확인하세요.");
      setStatus(
        "Pixiv 랭킹 데이터를 불러오지 못했습니다.\n" +
          "브라우저 콘솔(F12 > Console)에서 [pixiv_ranking] 로그를 확인해 주세요.\n" +
          "이 화면은 아직 실제 데이터 전달 방식이 확정되지 않아 임시 진단용으로 동작 중입니다."
      );
      return;
    }

    setStatus(null);
    renderItems(items);
  }

  // ---------------------------------------------------------------
  // 2) 렌더링 (탭 전환은 이미 받아온 items를 클라이언트에서 필터링)
  // ---------------------------------------------------------------

  function pickImage(item) {
    return (
      item.cover ||
      item.cover_url ||
      item.image_url ||
      item.image ||
      item.thumbnail ||
      item.thumbnail_url ||
      item.src ||
      ""
    );
  }

  function pickCategory(item) {
    return item.category || "전체";
  }

  function pickUrl(item) {
    return item.url || item.link || "#";
  }

  function renderItems(items) {
    const categories = ["전체"];
    for (const item of items) {
      const c = pickCategory(item);
      if (!categories.includes(c)) categories.push(c);
    }

    let activeCategory = "전체";

    function renderTabs() {
      els.tabs.innerHTML = "";
      for (const c of categories) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pxr-tab-btn" + (c === activeCategory ? " active" : "");
        btn.textContent = c;
        btn.addEventListener("click", () => {
          activeCategory = c;
          renderTabs();
          renderGrid();
        });
        els.tabs.appendChild(btn);
      }
    }

    function renderGrid() {
      els.grid.innerHTML = "";
      const filtered =
        activeCategory === "전체" ? items : items.filter((it) => pickCategory(it) === activeCategory);

      if (filtered.length === 0) {
        const empty = document.createElement("div");
        empty.className = "pxr-empty";
        empty.textContent = "표시할 항목이 없습니다.";
        els.grid.appendChild(empty);
        return;
      }

      for (const item of filtered) {
        const card = document.createElement("a");
        card.className = "pxr-card";
        card.href = pickUrl(item);
        card.target = "_blank";
        card.rel = "noopener noreferrer";

        const coverWrap = document.createElement("div");
        coverWrap.className = "pxr-card-cover";
        const img = document.createElement("img");
        img.src = pickImage(item);
        img.alt = item.title || "";
        img.loading = "lazy";
        coverWrap.appendChild(img);

        const body = document.createElement("div");
        body.className = "pxr-card-body";

        const title = document.createElement("div");
        title.className = "pxr-card-title";
        title.title = item.title || "";
        title.textContent = item.title || "";

        const author = document.createElement("div");
        author.className = "pxr-card-author";
        author.textContent = item.author || "";

        const badge = document.createElement("div");
        badge.className = "pxr-card-badge";
        badge.textContent = pickCategory(item);

        body.appendChild(title);
        body.appendChild(author);
        body.appendChild(badge);

        card.appendChild(coverWrap);
        card.appendChild(body);
        els.grid.appendChild(card);
      }
    }

    renderTabs();
    renderGrid();
  }

  // ---------------------------------------------------------------
  // 시작
  // ---------------------------------------------------------------
  if (els.root) {
    loadItems();
  } else {
    warn("루트 엘리먼트(#pixiv-ranking-root)를 찾지 못했습니다. index.html이 예상대로 마운트되지 않았을 수 있습니다.");
  }
})();
