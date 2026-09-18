// plugins/metadata/pixiv_ranking/dashboard.js
// 코어가 new Function('pluginId', 'shadowRoot', 'items', <이 파일 내용>) 형태로 실행한다.
// pluginId: 이 플러그인의 id ("pixiv_ranking")
// shadowRoot: 이 위젯 전용 Shadow DOM 루트 (dashboard.html이 이미 주입된 상태)
// items: get_dashboard_data(db_type, limit=1)이 이미 무작위로 골라서 반환해 준
//        항목 1개짜리 목록 (여러 장이 아니라 1장만 온다)
//
// 헤더/부제/캡션 없이 "이미지 카드" 하나만 보이도록 구성한다 (요청 반영):
// 순위 뱃지와 우상단의 작은 새로고침 버튼만 이미지 위에 얹는다.

var LOG_PREFIX = '[pixiv_ranking][home_widget]';
// home_widget.sessions="all"이라 어느 세션(일반/성인/오디오북/비디오)의 홈
// 화면에서도 이 위젯이 추가될 수 있다. 새로고침 버튼을 눌러 재조회할 때
// 쓸 설정 스코프는, 카테고리 탭(script.js)이 저장해 둔 것과 같은
// localStorage 키를 읽어 공유한다 (관리자가 실제로 PHPSESSID 등을
// 저장해 둔 스코프와 일치시키기 위함). 값이 없으면 'general'로 폴백.
var SCOPE_STORAGE_KEY = 'pixiv_ranking:config_scope';
var VALID_SCOPES = ['general', 'adult', 'audiobook', 'video'];

function getScope() {
  try {
    var saved = window.localStorage.getItem(SCOPE_STORAGE_KEY);
    if (saved && VALID_SCOPES.indexOf(saved) !== -1) return saved;
  } catch (e) {
    console.warn(LOG_PREFIX, 'localStorage 읽기 실패, 기본값(general) 사용:', e);
  }
  return 'general';
}

var cardEl = shadowRoot.querySelector('[data-role="card"]');
var linkEl = shadowRoot.querySelector('[data-role="link"]');
var imgEl = shadowRoot.querySelector('[data-role="img"]');
var rankEl = shadowRoot.querySelector('[data-role="rank"]');
var statusEl = shadowRoot.querySelector('[data-role="status"]');
var refreshBtn = shadowRoot.querySelector('[data-role="refresh"]');

function setStatus(text) {
  if (statusEl) statusEl.textContent = text || '';
}

function renderSingle(item) {
  cardEl.classList.remove('prw-img-error');
  setStatus('');
  rankEl.textContent = '';
  imgEl.removeAttribute('src');
  imgEl.alt = '';
  linkEl.href = '#';

  if (!item) {
    setStatus('표시할 이미지가 없습니다.');
    return;
  }

  linkEl.href = item.link || item.url || '#';
  // 동적 값은 DOM API로만 다루고 innerHTML에 직접 꽂지 않는다 (XSS 방어).
  imgEl.src = item.cover || item.image || item.image_url || '';
  imgEl.alt = item.title || '';

  if (item.rank) {
    rankEl.textContent = '#' + item.rank;
  }
}

imgEl.addEventListener('error', function () {
  console.warn(LOG_PREFIX, '이미지 로드 실패:', imgEl.alt, imgEl.src);
  cardEl.classList.add('prw-img-error');
  setStatus('이미지를 불러올 수 없습니다.');
});

function loadRandom() {
  setStatus('불러오는 중...');
  var scope = getScope();
  var params = new URLSearchParams({ type: scope, limit: '1' });
  var url = '/api/media/dashboard/widgets/' + pluginId + '/data?' + params.toString();

  console.log(LOG_PREFIX, '요청 시작 (scope=' + scope + '):', url);

  fetch(url, { credentials: 'same-origin' })
    .then(function (res) {
      return res.json().then(function (data) {
        return { status: res.status, data: data };
      });
    })
    .then(function (result) {
      console.log(LOG_PREFIX, '응답 수신:', result.status, result.data);
      var data = result.data;
      if (!data || data.success === false) {
        var errMsg = (data && data.error) || '이미지를 불러오지 못했습니다.';
        setStatus(errMsg);
        console.warn(LOG_PREFIX, '실패 응답:', errMsg);
        return;
      }
      var list = data.items || [];
      renderSingle(list[0]);
    })
    .catch(function (err) {
      console.error(LOG_PREFIX, '요청 실패:', err);
      setStatus('네트워크 오류로 이미지를 불러오지 못했습니다.');
    });
}

if (refreshBtn) {
  refreshBtn.addEventListener('click', function (ev) {
    ev.preventDefault();
    ev.stopPropagation();
    loadRandom();
  });
}

// 코어가 이미 조회해 넘겨준 초기 항목(랜덤 1장)을 그대로 렌더링한다.
// (혹시 비어 있으면 위젯 자체적으로 한 번 더 요청한다.)
if (items && items.length > 0) {
  renderSingle(items[0]);
} else {
  loadRandom();
}
