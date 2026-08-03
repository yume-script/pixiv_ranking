document.getElementById('load-btn').addEventListener('click', async () => {
    const mode = document.getElementById('mode-select').value;
    const content = document.getElementById('content-select').value;
    const grid = document.getElementById('pixiv-grid');
    
    grid.innerHTML = "로딩 중...";
    
    // 랭킹 목록 데이터 가져오기
    const res = await fetch(`/api/plugin/pixiv_ranking/get_pixiv_data?mode=${mode}&content=${content}`);
    const data = await res.json();
    
    grid.innerHTML = "";
    data.forEach(item => {
        // 이미지는 우리가 만든 proxy_image 엔드포인트를 통함
        const proxyUrl = `/api/plugin/pixiv_ranking/proxy_image?url=${encodeURIComponent(item.url)}`;
        
        grid.innerHTML += `
            <div class="pixiv-item">
                <img src="${proxyUrl}" loading="lazy">
                <p>${item.title}</p>
            </div>
        `;
    });
});
