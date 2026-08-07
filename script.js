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

// 이벤트 리스너 등록
document.getElementById('load-btn').addEventListener('click', fetchRanking);

// [중요] 페이지 로드 완료 시 일일/종합 랭킹 자동 실행
window.addEventListener('DOMContentLoaded', () => {
    console.log("[UI] 페이지 로드 완료, 초기 데이터 조회 시작");
    // 초기값 세팅 (일일/종합)
    document.getElementById('mode-select').value = 'daily';
    document.getElementById('content-select').value = 'all';
    fetchRanking();
});
