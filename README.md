# pixiv_ranking

git clone https://github.com/yume-script/pixiv_ranking

## 1.0.2 — 404 원인 해결 (아키텍처 수정)

서버 소스(`api/library.py`, `services/metadata_factory.py`,
`plugins/metadata/random_gallery/random_gallery.py`,
`plugins/metadata/aladin_bestseller/aladin_bestseller.py`) 대조로 확인된 내용:

- `category_tab`은 정식 코어 계약이며, `/api/media/category-plugins`가 사이드바
  메뉴를 만들고 `/api/media/plugins/<id>/ui`가 `index.html`/`style.css`/`script.js`를
  JSON 번들로 서빙합니다. (이 부분은 원래 코드도 맞았음)
- `/api/media/dashboard/widgets/<id>/data`는 `get_dashboard_data(db_type, limit)`만
  호출하며 `type`, `limit` 외 파라미터를 넘겨주지 않습니다.
- **mode/content처럼 커스텀 파라미터가 필요한 실시간 조회, 이미지 프록시는
  클래스 메서드로 만들어도 자동으로 라우팅되지 않습니다.** 반드시
  `aladin_bestseller.py`처럼 모듈 최상단에서 `@app.route(...)`로 직접 등록해야
  합니다. (`app`은 플러그인 로더가 모듈 네임스페이스에 주입해두므로 import 불필요)

### 변경 사항

- `pixiv_get()` / `proxy_image()` 클래스 메서드 제거 →
  `@app.route('/api/dashboard/pixiv-ranking')`,
  `@app.route('/api/dashboard/pixiv-ranking/image-proxy')`로 교체
- `script.js`의 `API_BASE`/`PROXY_BASE`를 위 절대경로로 수정
- `__init__.py`의 존재하지 않는 클래스명(`PixivRankingMetadataProvider`) import 버그 수정
  (실제 클래스명 `PixivRankingPlugin`)
- 필수 계약 `search()` / `apply()` 추가, (선택) `get_dashboard_data()`도 추가
- 이미지 프록시에 호스트 화이트리스트 추가 (오픈 프록시 악용 방지)
- `pixiv_ranking.py`를 `python pixiv_ranking.py --mode daily --content all`
  형태로 단독 CLI 실행도 가능하게 정리 (Flask/플러그인 베이스 없이도 동작)

### 배포 후 확인할 것

- 사이드바에 "Pixiv 랭킹" 메뉴가 뜨는지
- 탭 진입 시 자동으로 일일/종합 랭킹이 로드되는지
- 이미지 썸네일이 403 없이 정상 로드되는지 (image-proxy 경유)
