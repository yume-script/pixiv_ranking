// 랭킹 조회 로직을 별도 함수로 분리
async function fetchRanking() {
    const mode = document.getElementById('mode-select').value;
    const content = document.getElementById('content-select').value;
    const grid = document.getElementById('pixiv-grid');

    grid.innerHTML = "데이터 불러오는 중...";
    console.log(`[UI] 조회 시작: ${mode} / ${content}`);

    try {
        // 서버의 실제 API 엔드포인트 경로를 확인하여 수정하세요
        const response = await fetch(`pixiv_get.py?mode=${mode}&content=${content}`);
        if (!response.ok) throw new Error('서버 응답 오류: ' + response.status);

        const data = await response.json();
        grid.innerHTML = "";

        if (data.length === 0) {
            grid.innerHTML = "데이터가 없습니다. 플러그인 설정에서 PHPSESSID가 유효한지 확인하세요.";
            return;
        }

        data.forEach(item => {
            // 서버에서 이미 base64로 프리페치해 온 썸네일을 바로 사용
            // (item.image_data가 없으면 해당 이미지는 다운로드 실패한 것이므로 건너뜀)
            if (!item.image_data) return;

            grid.innerHTML += `
                <div class="pixiv-item">
                    <a href="${item.page_url}" target="_blank">
                        <img src="${item.image_data}"
                             data-original="${item.original_url}"
                             onerror="this.style.display='none'">
                    </a>
                    <p>${item.title}</p>
                </div>
            `;
        });
    } catch (e) {
        console.error(e);
        grid.innerHTML = "데이터 로드 실패. API 경로를 확인하세요.";
    }
}

// [중요] BookOasis는 SPA 방식으로 탭 전환 시 index.html/script.js를
// 이미 로드된 페이지 DOM에 나중에 동적으로 주입합니다.
// 이 시점엔 브라우저의 DOMContentLoaded 이벤트가 이미 지나간 뒤이므로
// window.addEventListener('DOMContentLoaded', ...) 는 절대 실행되지 않습니다.
// 대신 script.js가 실행되는 시점엔 자신의 index.html 요소들이
// 이미 DOM에 삽입되어 있으므로, 즉시 초기화를 실행합니다.
(function initPixivRankingView() {
    const loadBtn = document.getElementById('load-btn');
    if (!loadBtn) {
        console.error("[Pixiv][DEBUG] load-btn 요소를 찾을 수 없습니다. index.html 구조를 확인하세요.");
        return;
    }

    // 이벤트 리스너 등록
    loadBtn.addEventListener('click', fetchRanking);

    console.log("[UI] 플러그인 뷰 초기화 완료, 초기 데이터 조회 시작");
    // 초기값 세팅 (일일/종합)
    document.getElementById('mode-select').value = 'daily';
    document.getElementById('content-select').value = 'all';
    fetchRanking();
})();
