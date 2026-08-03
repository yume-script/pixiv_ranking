// Pixiv 랭킹 플러그인 - 카테고리 레벨 풀페이지 UI 로직
//
// index.html이 [플러그인] 카테고리 화면에 마운트되면, 이 스크립트가 아이템 데이터를
// 가져와 렌더링합니다. 코어는 플러그인이 자체 라우트를 만드는 걸 지원하지 않으므로,
// 이 fetch가 부르는 URL은 코어가 미리 제공하는 공용 엔드포인트일 것으로 추정하고
// 그럴듯한 후보들을 순서대로 시도합니다.
//
// 어떤 후보가 성공했는지는:
//   1) 브라우저 콘솔에 [pixiv_ranking] 로그로 남고
//   2) 성공 시 화면 상단에도 잠깐 파란 배너로 "사용된 URL: ..." 표시됩니다
// 이 정보를 알려주시면 나머지 후보 코드를 지우고 하나로 확정할 수 있습니다.

(function () {
  "use strict";

  const PLUGIN_ID = "pixiv_ranking";
  const LOG_PREFIX = "[pixiv_ranking]";

  const els = {
    root: document.getElementById("pixiv-ranking-root"),
    contentSelect: document.getElementById("pxr-content-select"),
    modeSelect: document.getElementById("pxr-mode-select"),
    grid: document.getElementById("pxr-grid"),
    status: document.getElementById("pxr-status"),
  };

  const ALL_LABEL = "전체";

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
    els.status.className = "pxr-status" + (mode ? " pxr-" + mode : "");
    els.status.textContent = message;
  }

  // ---------------------------------------------------------------
  // 0) 현재 페이지에서 db_type 등 힌트 추출 (URL 쿼리스트링 기반 추정)
  // ---------------------------------------------------------------
  function guessDbType() {
    const qs = new URLSearchParams(window.location.search);
    const candidates = ["db_type", "dbType", "db", "library_type", "libraryType"];
    for (const key of candidates) {
      const v = qs.get(key);
      if (v) return v;
    }
    return "general";
  }

  function guessLimit() {
    const qs = new URLSearchParams(window.location.search);
    const v = qs.get("limit");
    return v || "80";
  }

  // ---------------------------------------------------------------
  // 1) 데이터 소스 탐색: 내장 JSON/전역변수 먼저(비용 없음), 그다음 fetch 후보들
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
          log("내장 JSON 태그에서 데이터 발견:", id);
          return { payload: parsed, source: "embedded:#" + id };
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
        return { payload: window[name], source: "global:" + name };
      }
    }
    if (els.root && els.root.dataset && els.root.dataset.items) {
      try {
        log("root 엘리먼트 data-items 속성에서 데이터 발견");
        return { payload: JSON.parse(els.root.dataset.items), source: "data-items attribute" };
      } catch (e) {
        warn("data-items 파싱 실패:", e);
      }
    }
    return null;
  }

  async function tryFetchEndpoints() {
    const dbType = guessDbType();
    const limit = guessLimit();
    const qs1 = `db_type=${encodeURIComponent(dbType)}&limit=${encodeURIComponent(limit)}`;

    const candidateUrls = [
      // 플러그인 대시보드 데이터 조회용으로 흔히 쓰일 법한 REST 패턴들
      `/api/plugins/${PLUGIN_ID}/dashboard-data?${qs1}`,
      `/api/plugins/${PLUGIN_ID}/dashboard_data?${qs1}`,
      `/api/plugin/${PLUGIN_ID}/dashboard-data?${qs1}`,
      `/api/dashboard/plugin/${PLUGIN_ID}?${qs1}`,
      `/api/dashboard/${PLUGIN_ID}?${qs1}`,
      `/api/dashboard/widget/${PLUGIN_ID}?${qs1}`,
      `/dashboard/widget/${PLUGIN_ID}/data?${qs1}`,
      `/dashboard/widget/${PLUGIN_ID}?${qs1}`,
      `/plugins/${PLUGIN_ID}/dashboard-data?${qs1}`,
      `/plugin/${PLUGIN_ID}/dashboard-data?${qs1}`,
      `/api/plugins/${PLUGIN_ID}/data?${qs1}`,
      `/api/plugins/dashboard/${PLUGIN_ID}?${qs1}`,
      `/api/plugin-category/${PLUGIN_ID}?${qs1}`,
      `/api/plugin_category/${PLUGIN_ID}?${qs1}`,
    ];

    for (const url of candidateUrls) {
      try {
        const res = await fetch(url, { credentials: "same-origin" });
        if (!res.ok) {
          log("fetch 실패 (status " + res.status + "):", url);
          continue;
        }
        const contentType = res.headers.get("content-type") || "";
        if (!contentType.includes("application/json")) {
          log("fetch 응답이 JSON이 아님, 건너뜀:", url, contentType);
          continue;
        }
        const json = await res.json();
        log("fetch 성공:", url);
        return { payload: json, source: "fetch:" + url };
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

    let found = tryEmbeddedJsonScriptTag();
    if (!found) found = tryGlobalVariables();
    if (!found) found = await tryFetchEndpoints();

    const items = found ? extractItemsArray(found.payload) : null;

    if (!items || items.length === 0) {
      warn("어떤 방식으로도 데이터를 찾지 못했습니다. 아래 URL 후보들이 모두 실패/미스매치했습니다.");
      setStatus(
        "Pixiv 랭킹 데이터를 불러오지 못했습니다.\n" +
          "브라우저 콘솔(F12 > Console)의 [pixiv_ranking] 로그를 확인해서 실패한 URL 목록을 알려주세요.\n" +
          "정확한 데이터 엔드포인트가 확인되면 이 화면이 정상 동작하도록 코드가 단순화됩니다."
      );
      return;
    }

    setStatus("데이터 로드 성공 (소스: " + found.source + ") - 콘솔에서 자세히 확인 가능", "success");
    log("사용된 데이터 소스:", found.source, "/ 아이템 개수:", items.length);
    setTimeout(() => setStatus(null), 4000);

    renderItems(items);
  }

  // ---------------------------------------------------------------
  // 2) 렌더링 (드롭다운 필터링은 이미 받아온 items를 클라이언트에서 처리)
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

  function pickContentLabel(item) {
    return item.content_label || item.category || ALL_LABEL;
  }

  function pickModeLabel(item) {
    return item.mode_label || ALL_LABEL;
  }

  function pickUrl(item) {
    return item.url || item.link || "#";
  }

  function renderItems(items) {
    const contentToModes = new Map();
    for (const item of items) {
      const c = pickContentLabel(item);
      const m = pickModeLabel(item);
      if (!contentToModes.has(c)) contentToModes.set(c, new Set());
      contentToModes.get(c).add(m);
    }
    const contentLabels = Array.from(contentToModes.keys());

    function fillSelect(selectEl, options, selected) {
      selectEl.innerHTML = "";
      for (const opt of options) {
        const el = document.createElement("option");
        el.value = opt;
        el.textContent = opt;
        if (opt === selected) el.selected = true;
        selectEl.appendChild(el);
      }
    }

    function currentModeOptions() {
      const c = els.contentSelect.value;
      if (c === ALL_LABEL) {
        const all = new Set([ALL_LABEL]);
        for (const modes of contentToModes.values()) {
          for (const m of modes) all.add(m);
        }
        return Array.from(all);
      }
      return [ALL_LABEL, ...Array.from(contentToModes.get(c) || [])];
    }

    function refreshModeSelect() {
      const prevSelected = els.modeSelect.value || ALL_LABEL;
      const options = currentModeOptions();
      const nextSelected = options.includes(prevSelected) ? prevSelected : ALL_LABEL;
      fillSelect(els.modeSelect, options, nextSelected);
    }

    fillSelect(els.contentSelect, [ALL_LABEL, ...contentLabels], ALL_LABEL);
    refreshModeSelect();

    els.contentSelect.addEventListener("change", () => {
      refreshModeSelect();
      renderGrid();
    });
    els.modeSelect.addEventListener("change", () => {
      renderGrid();
    });

    function renderGrid() {
      els.grid.innerHTML = "";
      const contentVal = els.contentSelect.value;
      const modeVal = els.modeSelect.value;

      const filtered = items.filter((it) => {
        const contentOk = contentVal === ALL_LABEL || pickContentLabel(it) === contentVal;
        const modeOk = modeVal === ALL_LABEL || pickModeLabel(it) === modeVal;
        return contentOk && modeOk;
      });

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
        badge.textContent = pickContentLabel(item) + " · " + pickModeLabel(item);

        body.appendChild(title);
        body.appendChild(author);
        body.appendChild(badge);

        card.appendChild(coverWrap);
        card.appendChild(body);
        els.grid.appendChild(card);
      }
    }

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
