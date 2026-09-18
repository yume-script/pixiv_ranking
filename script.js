(function () {
  const LOG_PREFIX = '[Pixiv-Ranking-Plugin]';
  console.log(LOG_PREFIX, '0/3 Category-Level Fullpage UI loaded.');

  // 이 플러그인은 코어 도서 라이브러리와 무관한 외부(Pixiv) 데이터만 다루므로
  // category_tab.sessions="all"로 4개 세션(일반/성인/오디오북/비디오) 전부에
  // 노출된다. 다만 get_dashboard_data()가 읽는 플러그인 설정값(PHPSESSID 등)은
  // db_type 스코프별로 별도 저장되므로, 실제로 어느 스코프의 설정을 사용할지는
  // localStorage에 저장해 브라우저(=이 사용자) 전체에서 공유한다.
  // (홈 위젯 dashboard.js도 같은 키를 읽어 동일한 스코프를 사용함)
  const SCOPE_STORAGE_KEY = 'pixiv_ranking:config_scope';
  const VALID_SCOPES = ['general', 'adult', 'audiobook', 'video'];

  function getScope() {
    try {
      const saved = window.localStorage.getItem(SCOPE_STORAGE_KEY);
      if (saved && VALID_SCOPES.indexOf(saved) !== -1) return saved;
    } catch (e) {
      console.warn(LOG_PREFIX, 'localStorage 읽기 실패, 기본값(general) 사용:', e);
    }
    return 'general';
  }

  function setScope(value) {
    try {
      window.localStorage.setItem(SCOPE_STORAGE_KEY, value);
    } catch (e) {
      console.warn(LOG_PREFIX, 'localStorage 저장 실패:', e);
    }
  }

  function fetchRankingData() {
    const grid = document.getElementById('pr-grid');
    const status = document.getElementById('pr-status');
    const contentSelect = document.getElementById('pr-content-select');
    const modeSelect = document.getElementById('pr-mode-select');
    const scopeSelect = document.getElementById('pr-scope-select');
    if (!grid || !status) {
      console.warn(LOG_PREFIX, '컨테이너 엘리먼트(#pr-grid/#pr-status)를 찾지 못함');
      return;
    }

    const content = contentSelect ? contentSelect.value : 'all';
    const mode = modeSelect ? modeSelect.value : 'daily';
    const scope = scopeSelect ? scopeSelect.value : getScope();

    status.textContent = '불러오는 중...';
    status.style.display = 'block';
    grid.innerHTML = '';

    // 참고: random_gallery 플러그인과 동일한 엔드포인트 규격을 사용합니다.
    // /api/media/dashboard/widgets/{plugin_id}/data?type={db_type}&limit={limit}
    // 여기에 상단 드롭다운에서 고른 mode/content를 추가 쿼리 파라미터로 실어보냅니다.
    // (백엔드가 flask.request.args로 이 값을 읽어 설정값보다 우선 적용함)
    // type(=db_type)은 상단 "설정 적용 대상" 드롭다운에서 고른 스코프를 그대로
    // 사용한다. 코어가 현재 세션(일반/성인/오디오북/비디오)을 프론트엔드에
    // 자동으로 알려주는 공식 방법을 문서에서 찾지 못해, 사용자가 직접
    // 고르고 브라우저에 기억시키는 방식으로 확실하게 동작하도록 했다.
    const params = new URLSearchParams({
      type: scope,
      limit: '50',
      mode: mode,
      content: content,
    });
    const url = '/api/media/dashboard/widgets/pixiv_ranking/data?' + params.toString();

    console.log(LOG_PREFIX, '1/3 데이터 요청 시작 (scope=' + scope + '):', url);
    const t0 = performance.now();

    fetch(url)
      .then((res) => {
        console.log(LOG_PREFIX, '1/3 응답 수신: status=' + res.status);
        return res.json();
      })
      .then((data) => {
        const elapsed = ((performance.now() - t0) / 1000).toFixed(2);
        if (!data.success) {
          console.warn(LOG_PREFIX, '2/3 서버 오류 응답 (' + elapsed + 's):', data.error);
          status.textContent = '랭킹을 가져오지 못했습니다: ' + (data.error || '알 수 없는 오류');
          status.style.display = 'block';
          return;
        }
        const items = Array.isArray(data.items) ? data.items : [];
        console.log(
          LOG_PREFIX,
          '2/3 데이터 파싱 완료 (' + elapsed + 's): 항목 ' + items.length + '개'
        );
        renderGrid(items);
      })
      .catch((err) => {
        console.error(LOG_PREFIX, '1/3 요청 실패:', err);
        status.textContent = '서버 연결 오류';
        status.style.display = 'block';
      });
  }

  function renderGrid(items) {
    const grid = document.getElementById('pr-grid');
    const status = document.getElementById('pr-status');
    if (!grid || !status) return;
    grid.innerHTML = '';

    if (items.length === 0) {
      console.log(LOG_PREFIX, '3/3 표시할 항목 없음');
      status.textContent = '표시할 랭킹이 없습니다.';
      status.style.display = 'block';
      return;
    }
    status.style.display = 'none';

    let renderedCount = 0;
    let missingCoverCount = 0;

    items.forEach((item) => {
      const cover = item.cover || item.image || item.image_url || '';
      if (!cover) missingCoverCount += 1;

      const cell = document.createElement('a');
      cell.className = 'pr-cell';
      cell.href = item.link || item.url || '#';
      cell.target = '_blank';
      cell.rel = 'noopener noreferrer';

      const img = document.createElement('img');
      img.src = cover;
      img.alt = item.title || '';
      img.loading = 'lazy';
      img.addEventListener('error', () => {
        console.warn(LOG_PREFIX, '이미지 로드 실패:', item.title, cover.slice(0, 80));
      });
      cell.appendChild(img);

      if (item.rank) {
        const rankBadge = document.createElement('span');
        rankBadge.className = 'pr-rank-badge';
        rankBadge.textContent = '#' + item.rank;
        cell.appendChild(rankBadge);
      }

      if (item.title) {
        const caption = document.createElement('span');
        caption.className = 'pr-caption';
        caption.textContent = item.title;
        cell.appendChild(caption);
      }

      grid.appendChild(cell);
      renderedCount += 1;
    });

    console.log(
      LOG_PREFIX,
      '3/3 렌더링 완료: ' + renderedCount + '개 (cover 누락 ' + missingCoverCount + '개)'
    );
  }

  const refreshBtn = document.getElementById('pr-refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => {
      console.log(LOG_PREFIX, '새로고침 버튼 클릭');
      fetchRankingData();
    });
  }

  const contentSelectEl = document.getElementById('pr-content-select');
  if (contentSelectEl) {
    contentSelectEl.addEventListener('change', () => {
      console.log(LOG_PREFIX, '콘텐츠 타입 변경:', contentSelectEl.value);
      fetchRankingData();
    });
  }

  const modeSelectEl = document.getElementById('pr-mode-select');
  if (modeSelectEl) {
    modeSelectEl.addEventListener('change', () => {
      console.log(LOG_PREFIX, '랭킹 모드 변경:', modeSelectEl.value);
      fetchRankingData();
    });
  }

  const scopeSelectEl = document.getElementById('pr-scope-select');
  if (scopeSelectEl) {
    // 이전에 선택해 localStorage에 저장해둔 스코프를 드롭다운 초기값으로 복원.
    scopeSelectEl.value = getScope();
    scopeSelectEl.addEventListener('change', () => {
      console.log(LOG_PREFIX, '설정 적용 대상(스코프) 변경:', scopeSelectEl.value);
      setScope(scopeSelectEl.value);
      fetchRankingData();
    });
  }

  fetchRankingData();
})();
