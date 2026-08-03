document.getElementById('load-btn').addEventListener('click', async () => {
    const mode = document.getElementById('mode-select').value;
    const content = document.getElementById('content-select').value;
    const grid = document.getElementById('pixiv-grid');
    
    grid.innerHTML = "로딩 중...";
    
    // BookOasis의 플러그인 엔드포인트를 통해 파이썬 함수 호출
    const res = await fetch(`/api/plugin/pixiv_ranking/get_pixiv_data?mode=${mode}&content=${content}`);
    const data = await res.json();
    
    grid.innerHTML = "";
    data.forEach(item => {
        grid.innerHTML += `
            <div class="pixiv-item">
                <img src="${item.url}" loading="lazy">
                <p>${item.title}</p>
            </div>
        `;
    });
});

// 테마 동기화 모니터링
const themeObserver = new MutationObserver(() => {
    // 테마 변경 시 필요한 로직 추가 가능
});
themeObserver.observe(document.documentElement, { attributes: true });
