// 랭킹 조회 로직을 별도 함수로 분리
async function fetchRanking() {
    const mode = document.getElementById('mode-select').value;
    const content = document.getElementById('content-select').value;
    const grid = document.getElementById('pixiv-grid');
    
    grid.innerHTML = "데이터 불러오는 중...";
    console.log(`[UI] 조회 시작: ${mode} / ${content}`);
    
    try {
        // 서버의 실제 API 엔드포인트 경로를 확인하여 수정하세요
        // const response = await fetch(`/plugin/metadata/pixiv_ranking/pixiv_get.py?mode=${mode}&content=${content}`);
        const response = await fetch(`pixiv_get.py?mode=${mode}&content=${content}`);
        if (!response.ok) throw new Error('서버 응답 오류: ' + response.status);
        
        const data = await response.json();
        grid.innerHTML = "";
        
        data.forEach(item => {
            // 이미지 주소 처리 (필요시 프록시 엔드포인트 적용)
            grid.innerHTML += `
                <div class="pixiv-item">
                    <img src="${item.url}" loading="lazy" onerror="this.style.display='none'">
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
