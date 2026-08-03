document.getElementById('load-btn').addEventListener('click', async () => {
    const mode = document.getElementById('mode-select').value;
    const content = document.getElementById('content-select').value;
    const grid = document.getElementById('pixiv-grid');
    
    console.log(`[UI] 버튼 클릭: mode=${mode}, content=${content}`);
    grid.innerHTML = "데이터 불러오는 중...";
    
    try {
        console.log("[UI] API fetch 시도...");
        const response = await fetch(`/plugin/metadata/pixiv_ranking/pixiv_get.py?mode=${mode}&content=${content}`);
        
        console.log(`[UI] 응답 상태: ${response.status}`);
        if (!response.ok) throw new Error(`서버 응답 오류: ${response.statusText}`);
        
        const data = await response.json();
        console.log("[UI] JSON 데이터 파싱 완료:", data);

        if (!data || data.length === 0) {
            console.warn("[UI] 데이터가 비어있습니다.");
            grid.innerHTML = "데이터 없음";
            return;
        }

        grid.innerHTML = "";
        data.forEach((item, index) => {
            console.log(`[UI] 이미지 렌더링 시도 ${index + 1}: ${item.title}`);
            const proxyUrl = `/plugin/metadata/pixiv_ranking/proxy_image?url=${encodeURIComponent(item.url)}`;
            
            grid.innerHTML += `
                <div class="pixiv-item">
                    <img src="${proxyUrl}" loading="lazy" 
                         onload="console.log('[UI] 로딩 성공: ${item.title}')" 
                         onerror="console.error('[UI] 로딩 실패: ${item.url}'); this.style.display='none'">
                    <p>${item.title}</p>
                </div>
            `;
        });
        console.log("[UI] 렌더링 프로세스 종료");
    } catch (error) {
        console.error("[UI] 치명적 오류 발생:", error);
        grid.innerHTML = "오류 발생: " + error.message;
    }
});
