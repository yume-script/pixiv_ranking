import urllib.request
import urllib.parse
import json
import argparse
import sys

# 사용범
#python pixiv_get.py --mode daily --content all
#python pixiv_get.py --mode weekly --content illust
#python pixiv_get.py --mode monthly --content manga

def get_pixiv_ranking(mode, content):
    # Pixiv는 User-Agent가 없으면 요청을 차단하므로 헤더에 추가해야 합니다.
    url = f"https://www.pixiv.net/ranking.php?mode={mode}&content={content}&format=json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.pixiv.net/"
    }

    try:
        # Request 객체 생성
        req = urllib.request.Request(url, headers=headers)
        
        # 데이터 요청 및 응답 읽기
        with urllib.request.urlopen(req) as response:
            result = response.read().decode('utf-8')
            data = json.loads(result)
            
            # 데이터 추출
            contents = data.get('contents', [])
            if not contents:
                print("데이터를 찾을 수 없습니다. mode/content 값을 확인하세요.")
                return

            print(f"[{mode.upper()} / {content.upper()}] 랭킹 목록:")
            for item in contents:
                print(f"- {item.get('title')} | {item.get('url')}")
            
    except Exception as e:
        print(f"오류 발생: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pixiv 랭킹 크롤러 (urllib 버전)")
    parser.add_argument("--mode", required=True, help="daily, weekly, monthly, rookie 등")
    parser.add_argument("--content", required=True, help="all, illust, manga, ugoira 등")
    
    args = parser.parse_args()
    get_pixiv_ranking(args.mode, args.content)
