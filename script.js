// ⚠️ 아래 두 경로는 BookOasis 코어의 실제 라우팅 규칙에 맞춰 확인/수정이 필요합니다.
// (예: 플러그인 네임스페이스 하위 상대경로라고 가정한 값입니다.)
const API_BASE = "pixiv_get";
const PROXY_BASE = "proxy_image";

// 랭킹 조회 로직을 별도 함수로 분리
async function fetchRanking() {
    const mode = document.getElementById('mode-select').value;
    const content = document.getElementById('content-select').value;
    const grid = document.getElementById('pixiv-grid');

    grid.innerHTML = "데이터 불러오는 중...";
    console.log(`[UI] 조회 시작: ${mode} / ${content}`);

    try {
        const response = await fetch(
            `${API_BASE}?mode=${encodeURIComponent(mode)}&content=${encodeURIComponent(content)}`
        );
        if (!response.ok) throw new Error('서버 응답 오류: ' + response.status);

        const result = await response.json();

        // 서버가 {'success': True, 'items': [...]}로 래핑해서 주는 경우와
        // 배열을 그대로 주는 경우(이전 방식) 모두 대응
        if (result && result.success === false) {
            throw new Error(result.error || '알 수 없는 오류');
        }
        const items = Array.isArray(result) ? result : (result.items || []);

        grid.innerHTML = "";

        if (!items.length) {
            grid.innerHTML = "표시할 데이터가 없습니다.";
            return;
        }

        items.forEach(item => {
            // 이미지는 pixiv의 Referer 제한(직접 요청 시 403) 때문에
            // 반드시 서버 프록시(proxy_image)를 통해 로드합니다.
            const proxiedUrl = `${PROXY_BASE}?url=${encodeURIComponent(item.url)}`;
            grid.innerHTML += `
                <div class="pixiv-item">
                    <img src="${proxiedUrl}" loading="lazy" onerror="this.style.display='none'">
                    <p>${item.title}</p>
                </div>
            `;
        });
    } catch (e) {
        console.error(e);
        grid.innerHTML = "데이터 로드 실패: " + e.message;
    }
}

// 이벤트 리스너 등록
document.getElementById('load-btn').addEventListener('click', fetchRanking);

// 페이지 로드 완료 시 일일/종합 랭킹 자동 실행
window.addEventListener('DOMContentLoaded', () => {
    console.log("[UI] 페이지 로드 완료, 초기 데이터 조회 시작");
    document.getElementById('mode-select').value = 'daily';
    document.getElementById('content-select').value = 'all';
    fetchRanking();
});
