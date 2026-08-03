# pixiv_ranking

git clone https://github.com/yume-script/pixiv_ranking

## 1.0.1 변경 사항

- `__init__.py`가 존재하지 않는 클래스명(`PixivRankingMetadataProvider`)을 import하던 버그 수정
  (실제 클래스명 `PixivRankingPlugin`으로 정정 → 이전 버전은 플러그인 로딩 자체가 실패했음)
- 필수 계약 메서드 `search()` / `apply()` 추가
- 이미지 프록시(`proxy_image`)에 호스트 화이트리스트 추가 (오픈 프록시 악용 방지)
- `script.js`: 이미지 로딩을 반드시 `proxy_image`를 통하도록 변경
  (pixiv 이미지 서버는 Referer 헤더가 없으면 403을 반환하므로 원본 URL 직접 로드는 대부분 실패함)
- `script.js`: API/프록시 경로를 상수(`API_BASE`, `PROXY_BASE`)로 분리, 에러/빈 데이터 처리 보강

## ⚠️ 배포 전 반드시 확인해야 할 두 가지

1. **`category_tab` 필드**: `guide_plugins.md`에는 문서화되어 있지 않은 필드입니다.
   문서상 공식 계약은 `dashboard_widget = {..., 'all_desk_tab': True}` + `get_dashboard_data()`입니다.
   실제 코어가 `category_tab`을 인식하는지 확인 후, 아니라면 문서화된 방식으로 교체하세요.
2. **`pixiv_get` / `proxy_image` 라우트 경로**: 코어가 이 커스텀 메서드들을 실제로 어떤 URL로
   노출하는지에 따라 `script.js`의 `API_BASE`, `PROXY_BASE` 값을 맞춰서 수정해야 합니다.
