"""
약식 규모검토 계산기 (All-in-One)
여러 용도지역 처리 개선 버전

실행:
  python3 web_app_unified.py            # 일반 모드
  python3 web_app_unified.py --debug    # 서버 디버그 모드

브라우저에서:
  F12 → Console 탭에서 로그 확인 가능
"""

import io, json, sys, os, threading, base64, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs
from typing import Dict, Any


# ══════════════════════════════════════════════════════════════════
# 용도지역 자동 조회 모듈
# ══════════════════════════════════════════════════════════════════

import re
import json
import ssl
import urllib.parse
import urllib.request
from typing import Optional, Dict, Tuple
import sys

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

VWORLD_API_KEY = "DB07E3CD-6F12-388C-99D4-6779EA88652F"
VWORLD_REFERER = os.environ.get("VWORLD_REFERER", "http://localhost")
_pnu_cache: Dict[str, Optional[str]] = {}
DEBUG_MODE = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")

def log_debug(msg: str):
    """디버그 메시지를 stderr에 출력 (항상 출력하여 Render 로그에서 확인 가능)"""
    print(f"[DEBUG] {msg}", file=sys.stderr)

def geocode_address(address: str) -> Optional[Dict]:
    log_debug(f"1. Geocoding 시작: {address}")
    params = urllib.parse.urlencode({
        "service": "address", "request": "getcoord", "version": "2.0",
        "crs": "epsg:4326", "address": address, "refine": "true",
        "simple": "false", "format": "json", "type": "PARCEL",
        "key": VWORLD_API_KEY,
    })
    url = f"https://api.vworld.kr/req/address?{params}"
    try:
        req = urllib.request.Request(url)
        req.add_header("Referer", VWORLD_REFERER)
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        status = data.get("response", {}).get("status")
        log_debug(f"   Geocoding 응답: {status}")
        if status == "OK":
            return data["response"]
        else:
            log_debug(f"   실패 응답: {data}")
    except Exception as e:
        log_debug(f"   오류: {e}")
    return None

def parse_jibun(jibun_str: str) -> Tuple[int, int]:
    jibun_str = jibun_str.replace("산", "").strip()
    match = re.search(r"(\d+)(?:-(\d+))?", jibun_str)
    if match:
        main_num = int(match.group(1))
        sub_num = int(match.group(2)) if match.group(2) else 0
        return main_num, sub_num
    return 0, 0

def get_pnu_from_coord(x: float, y: float) -> Optional[str]:
    log_debug(f"2. PNU 조회: x={x}, y={y}")
    params = urllib.parse.urlencode({
        "service": "address", "request": "getAddress", "version": "2.0",
        "crs": "epsg:4326", "point": f"{x},{y}", "format": "json",
        "type": "PARCEL", "key": VWORLD_API_KEY,
    })
    url = f"https://api.vworld.kr/req/address?{params}"
    try:
        req = urllib.request.Request(url)
        req.add_header("Referer", VWORLD_REFERER)
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("response", {}).get("status") == "OK":
            results = data["response"]["result"]
            item = results[0] if isinstance(results, list) else results
            structure = item.get("structure", {})
            level5 = structure.get("level5", "")
            level4LC = structure.get("level4LC", "")
            main_num, sub_num = parse_jibun(level5)
            land_type = "2" if "산" in level5 else "1"
            if level4LC and len(level4LC) == 10:
                pnu = f"{level4LC}{land_type}{main_num:04d}{sub_num:04d}"
                log_debug(f"   PNU 생성: {pnu}")
                return pnu
            else:
                log_debug(f"   level4LC 없음: {level4LC}")
    except Exception as e:
        log_debug(f"   오류: {e}")
    return None

def address_to_pnu(address: str) -> Optional[str]:
    if address in _pnu_cache:
        cached = _pnu_cache[address]
        log_debug(f"캐시 PNU: {cached}")
        return cached
    
    geo = geocode_address(address)
    if not geo:
        log_debug("Geocoding 실패")
        return None
    
    result = geo.get("result", {})
    point = result.get("point", {})
    x, y = point.get("x"), point.get("y")
    
    if not x or not y:
        log_debug(f"좌표 없음: x={x}, y={y}")
        return None
    
    pnu = get_pnu_from_coord(float(x), float(y))
    if pnu:
        _pnu_cache[address] = pnu
    return pnu

def method2_vworld_api(address: str) -> Optional[str]:
    log_debug(f"\n{'='*50}")
    log_debug(f"용도지역 조회 시작: {address}")
    log_debug(f"{'='*50}")
    
    pnu = address_to_pnu(address)
    
    if not pnu:
        log_debug("❌ PNU 생성 실패")
        return None
    
    log_debug(f"3. 용도지역 API 호출")
    log_debug(f"   PNU: {pnu}")
    
    params = urllib.parse.urlencode({
        "key": VWORLD_API_KEY, "pnu": pnu,
        "numOfRows": "100", "format": "json",
    })
    url = f"https://api.vworld.kr/ned/data/getLandUseAttr?{params}"

    try:
        req = urllib.request.Request(url)
        req.add_header("Referer", VWORLD_REFERER)
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        
        land_uses = data.get("landUses", {})
        result_code = land_uses.get("resultCode", "")
        
        log_debug(f"   resultCode: {result_code}")
        
        fields = land_uses.get("field", [])
        if not isinstance(fields, list):
            fields = [fields]
        
        log_debug(f"   field 개수: {len(fields)}")
        
        if not fields:
            log_debug("❌ fields 데이터 없음")
            return None
        
        yongdo_zones = []
        for field in fields:
            code = field.get("prposAreaDstrcCode", "")
            name = field.get("prposAreaDstrcCodeNm", "")
            log_debug(f"   - {name} ({code})")
            if name and code.startswith("UQA"):
                yongdo_zones.append(name)
        
        if yongdo_zones:
            broad = {"도시지역","관리지역","농림지역","자연환경보전지역",
                     "주거지역","상업지역","공업지역","녹지지역","용도미지정"}
            specific = [n for n in yongdo_zones if n not in broad]
            if specific:
                seen = set()
                unique = [s for s in specific if not (s in seen or seen.add(s))]
                result = ", ".join(unique)
                log_debug(f"✅ 결과 ({len(unique)}개): {result}")
                return result
            result = ", ".join(yongdo_zones)
            log_debug(f"✅ 결과(대분류): {result}")
            return result
        
        all_names = [f.get("prposAreaDstrcCodeNm","") for f in fields if f.get("prposAreaDstrcCodeNm")]
        if all_names:
            result = ", ".join(all_names)
            log_debug(f"✅ 결과(전체): {result}")
            return result
        
        log_debug("❌ 용도지역 정보 없음")
        return None
        
    except Exception as e:
        log_debug(f"❌ API 오류: {e}")
        import traceback
        log_debug(traceback.format_exc())
        return None



def method1_eum_scraping(address: str) -> Optional[str]:
    """토지이음 사이트에서 PNU를 사용해 용도지역을 스크래핑 (Selenium)"""
    log_debug(f"[방법 1] 토지이음 스크래핑 시작: {address}")

    pnu = address_to_pnu(address)
    if not pnu:
        log_debug("❌ PNU 생성 실패")
        return None

    log_debug(f"   PNU: {pnu}")

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service as ChromeService
        from selenium.webdriver.common.by import By
    except ImportError:
        log_debug("❌ selenium 패키지 없음")
        return None

    import time as _time

    url = (
        f"https://www.eum.go.kr/web/ar/lu/luLandDet.jsp"
        f"?pnu={pnu}&mode=search&isNoScr=script&selGbn=umd"
    )
    log_debug(f"   URL: {url}")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    # 환경변수로 Chromium 경로가 지정된 경우 (Docker/클라우드 배포용)
    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        options.binary_location = chrome_bin

    driver = None
    try:
        # chromedriver 경로가 환경변수로 지정된 경우 Service 사용
        chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
        if chromedriver_path:
            service = ChromeService(executable_path=chromedriver_path)
            driver = webdriver.Chrome(service=service, options=options)
        else:
            driver = webdriver.Chrome(options=options)
        driver.get(url)
        _time.sleep(5)

        # JavaScript 변수에서 용도지역 데이터 추출
        try:
            seh_data = driver.execute_script(
                "return typeof sehUcodeListExt !== 'undefined' ? sehUcodeListExt : null;"
            )
            if seh_data:
                log_debug(f"   sehUcodeListExt: {seh_data}")
                zones = extract_zones_from_seh(seh_data)
                if zones:
                    return zones
        except Exception:
            pass

        # 페이지 소스에서 직접 추출
        page_source = driver.page_source
        match = re.search(r'var\s+sehUcodeListExt\s*=\s*["\x27](.+?)["\x27];', page_source)
        if match:
            seh_raw = match.group(1)
            log_debug(f"   sehUcodeListExt (소스): {seh_raw}")
            zones = extract_zones_from_seh(seh_raw)
            if zones:
                return zones

        # 페이지에서 용도지역 관련 텍스트 직접 추출
        try:
            elements = driver.find_elements(By.XPATH, "//*[contains(text(), '지역')]")
            zone_names = []
            for el in elements:
                text = el.text.strip()
                if any(kw in text for kw in ["주거지역", "상업지역", "공업지역",
                                               "녹지지역", "관리지역", "농림지역",
                                               "자연환경보전지역"]):
                    zone_names.append(text)
            if zone_names:
                seen = set()
                unique = [z for z in zone_names if not (z in seen or seen.add(z))]
                return ", ".join(unique)
        except Exception:
            pass

        log_debug("❌ 토지이음에서 용도지역 정보를 찾을 수 없음")
        return None

    except Exception as e:
        log_debug(f"❌ 토지이음 오류: {e}")
        return None
    finally:
        if driver:
            driver.quit()


def extract_zones_from_seh(seh_data: str) -> Optional[str]:
    """sehUcodeListExt 데이터에서 용도지역명을 추출"""
    names = re.findall(r'uname=([^,}\]]+)', seh_data)
    if not names:
        try:
            items = json.loads(seh_data.replace("'", '"'))
            names = [item.get("uname", "") for item in items if item.get("uname")]
        except Exception:
            pass

    if not names:
        return None

    names = [n.strip() for n in names]

    if len(names) >= 2:
        return names[1]  # 구체적 용도지역 (예: 제2종일반주거지역)

    return names[0]


DEFAULT_PORT = int(os.environ.get("PORT", 8080))
DEFAULT_HOST = "0.0.0.0"

_HTML_B64 = """PCFET0NUWVBFIGh0bWw+CjxodG1sIGxhbmc9ImtvIj4KPGhlYWQ+CjxtZXRhIGNoYXJzZXQ9IlVURi04Ij4KPG1ldGEgbmFtZT0idmlld3BvcnQiIGNvbnRlbnQ9IndpZHRoPWRldmljZS13aWR0aCwgaW5pdGlhbC1zY2FsZT0xLjAiPgo8dGl0bGU+6rG07LaVIOq3nOuqqOqygO2GoDwvdGl0bGU+CjxzY3JpcHQgY3Jvc3NvcmlnaW4gc3JjPSJodHRwczovL3VucGtnLmNvbS9yZWFjdEAxOC91bWQvcmVhY3QucHJvZHVjdGlvbi5taW4uanMiPjwvc2NyaXB0Pgo8c2NyaXB0IGNyb3Nzb3JpZ2luIHNyYz0iaHR0cHM6Ly91bnBrZy5jb20vcmVhY3QtZG9tQDE4L3VtZC9yZWFjdC1kb20ucHJvZHVjdGlvbi5taW4uanMiPjwvc2NyaXB0Pgo8c2NyaXB0IHNyYz0iaHR0cHM6Ly91bnBrZy5jb20vQGJhYmVsL3N0YW5kYWxvbmUvYmFiZWwubWluLmpzIj48L3NjcmlwdD4KPHN0eWxlPgoqe21hcmdpbjowO3BhZGRpbmc6MDtib3gtc2l6aW5nOmJvcmRlci1ib3g7fQpib2R5e2ZvbnQtZmFtaWx5Oi1hcHBsZS1zeXN0ZW0sQmxpbmtNYWNTeXN0ZW1Gb250LCdTZWdvZSBVSScsc2Fucy1zZXJpZjtiYWNrZ3JvdW5kOmxpbmVhci1ncmFkaWVudCgxMzVkZWcsIzY2N2VlYSwjNzY0YmEyKTtwYWRkaW5nOjIwcHg7fQouY29udGFpbmVye21heC13aWR0aDoxMjAwcHg7bWFyZ2luOjAgYXV0bztiYWNrZ3JvdW5kOiNmZmY7Ym9yZGVyLXJhZGl1czoxNnB4O2JveC1zaGFkb3c6MCAyMHB4IDYwcHggcmdiYSgwLDAsMCwuMyk7fQouaGVhZGVye2JhY2tncm91bmQ6bGluZWFyLWdyYWRpZW50KDEzNWRlZywjNjY3ZWVhLCM3NjRiYTIpO2NvbG9yOiNmZmY7cGFkZGluZzoyNHB4O3RleHQtYWxpZ246Y2VudGVyO2JvcmRlci1yYWRpdXM6MTZweCAxNnB4IDAgMDt9Ci5oZWFkZXIgaDF7Zm9udC1zaXplOjI0cHg7Zm9udC13ZWlnaHQ6NzAwO21hcmdpbi1ib3R0b206NHB4O30KLmhlYWRlciBwe2ZvbnQtc2l6ZToxM3B4O29wYWNpdHk6Ljg1O30KLmNvbnRlbnR7cGFkZGluZzoyNHB4O30KLnNlY3Rpb257bWFyZ2luLWJvdHRvbToyNHB4O3BhZGRpbmc6MjBweDtiYWNrZ3JvdW5kOiNmOWZhZmI7Ym9yZGVyLXJhZGl1czoxMnB4O2JvcmRlcjoycHggc29saWQgI2U1ZTdlYjt9Ci5zZWN0aW9uLXRpdGxle2ZvbnQtc2l6ZToxNnB4O2ZvbnQtd2VpZ2h0OjcwMDtjb2xvcjojMzc0MTUxO21hcmdpbi1ib3R0b206MTZweDtwYWRkaW5nLWJvdHRvbTo4cHg7Ym9yZGVyLWJvdHRvbToycHggc29saWQgI2QxZDVkYjt9Ci5ncmlke2Rpc3BsYXk6Z3JpZDtnYXA6MTZweDt9Ci5ncmlkLTJ7Z3JpZC10ZW1wbGF0ZS1jb2x1bW5zOjFmciAxZnI7fQouZ3JpZC0ze2dyaWQtdGVtcGxhdGUtY29sdW1uczpyZXBlYXQoMywxZnIpO30KQG1lZGlhKG1heC13aWR0aDo3NjhweCl7LmdyaWQtMiwuZ3JpZC0ze2dyaWQtdGVtcGxhdGUtY29sdW1uczoxZnI7fX0KLmZpZWxke2Rpc3BsYXk6ZmxleDtmbGV4LWRpcmVjdGlvbjpjb2x1bW47fQouZmllbGQgbGFiZWx7Zm9udC1zaXplOjEycHg7Zm9udC13ZWlnaHQ6NzAwO2NvbG9yOiM0YjU1NjM7bWFyZ2luLWJvdHRvbTo2cHg7fQouZmllbGQgbGFiZWwgLmJhZGdle21hcmdpbi1sZWZ0OjhweDtmb250LXdlaWdodDo0MDA7Y29sb3I6IzEwYjk4MTt9Ci5maWVsZCBpbnB1dCwuZmllbGQgc2VsZWN0e3BhZGRpbmc6MTBweCAxMnB4O2JvcmRlcjoycHggc29saWQgI2QxZDVkYjtib3JkZXItcmFkaXVzOjhweDtmb250LXNpemU6MTRweDtvdXRsaW5lOm5vbmU7fQouZmllbGQgaW5wdXQ6Zm9jdXMsLmZpZWxkIHNlbGVjdDpmb2N1c3tib3JkZXItY29sb3I6IzY2N2VlYTt9Ci5maWVsZCBpbnB1dFt0eXBlPW51bWJlcl17Zm9udC12YXJpYW50LW51bWVyaWM6dGFidWxhci1udW1zO30KLmluZm8tYm94e3BhZGRpbmc6MTJweDtiYWNrZ3JvdW5kOiNlZmY2ZmY7Ym9yZGVyOjFweCBzb2xpZCAjYmZkYmZlO2JvcmRlci1yYWRpdXM6OHB4O2ZvbnQtc2l6ZToxM3B4O2NvbG9yOiMxZTQwYWY7fQouaW5mby1yb3d7ZGlzcGxheTpmbGV4O2p1c3RpZnktY29udGVudDpzcGFjZS1iZXR3ZWVuO3BhZGRpbmc6OHB4IDA7Ym9yZGVyLWJvdHRvbToxcHggc29saWQgI2RiZWFmZTt9Ci5pbmZvLXJvdzpsYXN0LWNoaWxke2JvcmRlcjpub25lO30KLmluZm8tbGFiZWx7Y29sb3I6IzNiODJmNjtmb250LXdlaWdodDo2MDA7fQouaW5mby12YWx1ZXtjb2xvcjojMWU0MGFmO2ZvbnQtd2VpZ2h0OjcwMDt9Ci5idG4tcm93e2Rpc3BsYXk6ZmxleDtnYXA6OHB4O21hcmdpbi10b3A6OHB4O30KLmJ0bntmbGV4OjE7cGFkZGluZzoxMnB4O2JvcmRlcjpub25lO2JvcmRlci1yYWRpdXM6OHB4O2ZvbnQtc2l6ZToxNHB4O2ZvbnQtd2VpZ2h0OjYwMDtjdXJzb3I6cG9pbnRlcjt0cmFuc2l0aW9uOmFsbCAuMnM7fQouYnRuLWJsdWV7YmFja2dyb3VuZDojM2I4MmY2O2NvbG9yOiNmZmY7fQouYnRuLWJsdWU6aG92ZXJ7YmFja2dyb3VuZDojMjU2M2ViO30KLmJ0bi1ibHVlOmRpc2FibGVke2JhY2tncm91bmQ6IzkzYzVmZDtjdXJzb3I6bm90LWFsbG93ZWQ7fQouYnRuLWdyZWVue2JhY2tncm91bmQ6IzEwYjk4MTtjb2xvcjojZmZmO30KLmJ0bi1ncmVlbjpob3ZlcntiYWNrZ3JvdW5kOiMwNTk2Njk7fQouYnRuLXJlZHtiYWNrZ3JvdW5kOiNlZjQ0NDQ7Y29sb3I6I2ZmZjtwYWRkaW5nOjhweCAxMnB4O2ZvbnQtc2l6ZToxMnB4O30KLmJ0bi1yZWQ6aG92ZXJ7YmFja2dyb3VuZDojZGMyNjI2O30KLmJ0bi1hZGR7YmFja2dyb3VuZDojOGI1Y2Y2O2NvbG9yOiNmZmY7cGFkZGluZzoxMHB4IDE2cHg7Zm9udC1zaXplOjEzcHg7bWFyZ2luLXRvcDoxMnB4O30KLmJ0bi1hZGQ6aG92ZXJ7YmFja2dyb3VuZDojN2MzYWVkO30KLnN0YXR1c3ttYXJnaW4tdG9wOjhweDtwYWRkaW5nOjEwcHggMTJweDtib3JkZXItcmFkaXVzOjZweDtmb250LXNpemU6MTJweDtmb250LXdlaWdodDo1MDA7fQouc3QtaXtiYWNrZ3JvdW5kOiNlZmY2ZmY7Ym9yZGVyOjFweCBzb2xpZCAjYmZkYmZlO2NvbG9yOiMxZDRlZDg7fQouc3Qtb2t7YmFja2dyb3VuZDojZjBmZGY0O2JvcmRlcjoxcHggc29saWQgI2JiZjdkMDtjb2xvcjojMTU4MDNkO30KLnN0LWVycntiYWNrZ3JvdW5kOiNmZWYyZjI7Ym9yZGVyOjFweCBzb2xpZCAjZmVjYWNhO2NvbG9yOiNiOTFjMWM7fQouc3Qtd2FybntiYWNrZ3JvdW5kOiNmZmZiZWI7Ym9yZGVyOjFweCBzb2xpZCAjZmRlNjhhO2NvbG9yOiM5MjQwMGU7fQoucmF3e21hcmdpbi10b3A6NnB4O3BhZGRpbmc6OHB4IDEycHg7YmFja2dyb3VuZDojZmZmO2JvcmRlcjoxcHggc29saWQgI2U1ZTdlYjtib3JkZXItcmFkaXVzOjZweDtmb250LXNpemU6MTJweDtjb2xvcjojNmI3MjgwO30KLnJhdyBzdHJvbmd7Y29sb3I6IzRmNDZlNTt9Ci5tdWx0aS16b25le3BhZGRpbmc6MTZweDtiYWNrZ3JvdW5kOiNkYmVhZmU7Ym9yZGVyOjJweCBzb2xpZCAjM2I4MmY2O2JvcmRlci1yYWRpdXM6MTJweDttYXJnaW4tdG9wOjEycHg7fQoubXVsdGktem9uZSBoNHtmb250LXNpemU6MTRweDtjb2xvcjojMWU0MGFmO21hcmdpbi1ib3R0b206MTJweDtmb250LXdlaWdodDo3MDA7fQouem9uZS1yb3d7ZGlzcGxheTpncmlkO2dyaWQtdGVtcGxhdGUtY29sdW1uczphdXRvIDFmciAxZnIgYXV0bztnYXA6MTJweDthbGlnbi1pdGVtczpjZW50ZXI7bWFyZ2luLWJvdHRvbToxMnB4O3BhZGRpbmc6MTJweDtiYWNrZ3JvdW5kOiNmZmY7Ym9yZGVyLXJhZGl1czo4cHg7fQouem9uZS1yb3cgLmxhYmVse2ZvbnQtc2l6ZToxM3B4O2ZvbnQtd2VpZ2h0OjcwMDtjb2xvcjojNGI1NTYzO21pbi13aWR0aDo2MHB4O30KQG1lZGlhKG1heC13aWR0aDo3NjhweCl7LnpvbmUtcm93e2dyaWQtdGVtcGxhdGUtY29sdW1uczoxZnI7Z2FwOjhweDt9LnpvbmUtcm93IC5sYWJlbHttYXJnaW4tYm90dG9tOjRweDt9fQoucmVzdWx0c3tiYWNrZ3JvdW5kOiNmMGZkZjQ7Ym9yZGVyOjJweCBzb2xpZCAjYmJmN2QwO3BhZGRpbmc6MjBweDtib3JkZXItcmFkaXVzOjEycHg7fQoucmVzdWx0cyBoM3tmb250LXNpemU6MThweDtjb2xvcjojMTU4MDNkO21hcmdpbi1ib3R0b206MTZweDt9Ci5tZXRyaWN7ZGlzcGxheTpmbGV4O2p1c3RpZnktY29udGVudDpzcGFjZS1iZXR3ZWVuO3BhZGRpbmc6MTJweDtiYWNrZ3JvdW5kOiNmZmY7Ym9yZGVyLXJhZGl1czo4cHg7bWFyZ2luLWJvdHRvbTo4cHg7fQoubWV0cmljLWxhYmVse2ZvbnQtc2l6ZToxM3B4O2NvbG9yOiM2YjcyODA7fQoubWV0cmljLXZhbHVle2ZvbnQtc2l6ZToxOHB4O2ZvbnQtd2VpZ2h0OjcwMDtjb2xvcjojMWYyOTM3O30KdGFibGV7d2lkdGg6MTAwJTtib3JkZXItY29sbGFwc2U6Y29sbGFwc2U7bWFyZ2luLXRvcDoxNnB4O2ZvbnQtc2l6ZToxM3B4O30KdGgsdGR7cGFkZGluZzoxMHB4IDEycHg7dGV4dC1hbGlnbjpyaWdodDtib3JkZXI6MXB4IHNvbGlkICNlNWU3ZWI7fQp0aHtiYWNrZ3JvdW5kOiNmM2Y0ZjY7Zm9udC13ZWlnaHQ6NzAwO2NvbG9yOiMzNzQxNTE7fQp0ZHtiYWNrZ3JvdW5kOiNmZmY7fQp0ZDpmaXJzdC1jaGlsZCx0aDpmaXJzdC1jaGlsZHt0ZXh0LWFsaWduOmxlZnQ7Zm9udC13ZWlnaHQ6NjAwO30KLnRvdGFsLXJvd3tiYWNrZ3JvdW5kOiNmZWYzYzchaW1wb3J0YW50O2ZvbnQtd2VpZ2h0OjcwMDt9Ci5oaWdobGlnaHQtcm93e2JhY2tncm91bmQ6I2RiZWFmZSFpbXBvcnRhbnQ7fQouc3ViLXJvd3tiYWNrZ3JvdW5kOiNmOWZhZmIhaW1wb3J0YW50O30KLnN1Yi1yb3cgdGQ6Zmlyc3QtY2hpbGR7cGFkZGluZy1sZWZ0OjI4cHg7Y29sb3I6IzZiNzI4MDt9Ci5hc3N1bXB0aW9uc3tkaXNwbGF5OmdyaWQ7Z3JpZC10ZW1wbGF0ZS1jb2x1bW5zOnJlcGVhdCgyLDFmcik7Z2FwOjEycHg7bWFyZ2luLXRvcDoxMnB4O30KQG1lZGlhKG1heC13aWR0aDo3NjhweCl7LmFzc3VtcHRpb25ze2dyaWQtdGVtcGxhdGUtY29sdW1uczoxZnI7fX0KLmFzc3VtcHRpb24taXRlbXtkaXNwbGF5OmZsZXg7YWxpZ24taXRlbXM6Y2VudGVyO2dhcDo4cHg7fQouYXNzdW1wdGlvbi1pdGVtIGxhYmVse2ZsZXg6MTtmb250LXNpemU6MTJweDtjb2xvcjojNGI1NTYzO30KLmFzc3VtcHRpb24taXRlbSBpbnB1dHt3aWR0aDo4MHB4O3BhZGRpbmc6NnB4IDhweDtib3JkZXI6MXB4IHNvbGlkICNkMWQ1ZGI7Ym9yZGVyLXJhZGl1czo2cHg7dGV4dC1hbGlnbjpyaWdodDt9Cjwvc3R5bGU+CjwvaGVhZD4KPGJvZHk+CjxkaXYgaWQ9InJvb3QiPjwvZGl2Pgo8c2NyaXB0IHR5cGU9InRleHQvYmFiZWwiPgpjb25zdCB7dXNlU3RhdGUsdXNlRWZmZWN0fT1SZWFjdDsKCmNvbnN0IFpPTkVTPXsKICAn7J2867CY7KO86rGw7KeA7JetXzLsooUnOntsZWdhbENvdmVyYWdlOjAuNixsZWdhbEZBUjoyLjUsYXBwbGllZENvdmVyYWdlOjAuNTUsYXBwbGllZEZBUjoyLjQ5fSwKICAn7J2867CY7KO86rGw7KeA7JetXzPsooUnOntsZWdhbENvdmVyYWdlOjAuNSxsZWdhbEZBUjozLjAsYXBwbGllZENvdmVyYWdlOjAuNCxhcHBsaWVkRkFSOjIuOTl9LAogICfspIDso7zqsbDsp4Dsl60nOntsZWdhbENvdmVyYWdlOjAuNixsZWdhbEZBUjo0LjAsYXBwbGllZENvdmVyYWdlOjAuNTUsYXBwbGllZEZBUjozLjk5fSwKICAn7J2867CY7IOB7JeF7KeA7JetJzp7bGVnYWxDb3ZlcmFnZTowLjYsbGVnYWxGQVI6OC4wLGFwcGxpZWRDb3ZlcmFnZTowLjU1LGFwcGxpZWRGQVI6Ny45OX0KfTsKCmNvbnN0IFVTRV9UWVBFUz17CiAgJ+yehOuMgO2Yleq4sOyImeyCrCc6e2Rvcm06MSxvZmZpY2V0ZWw6MCxob3RlbDowLHJldGFpbDowfSwKICAn6rSA6rSR7Zi47YWUJzp7ZG9ybTowLG9mZmljZXRlbDowLGhvdGVsOjEscmV0YWlsOjB9LAogICfsmKTtlLzsiqTthZQnOntkb3JtOjAsb2ZmaWNldGVsOjEsaG90ZWw6MCxyZXRhaWw6MH0sCiAgJ+yehOuMgO2Yleq4sOyImeyCrCvqt7zsg50nOntkb3JtOjAuNzUsb2ZmaWNldGVsOjAsaG90ZWw6MCxyZXRhaWw6MC4yNX0sCiAgJ+yehOuMgO2Yleq4sOyImeyCrCvqtIDqtJHtmLjthZQnOntkb3JtOjAuNzUsb2ZmaWNldGVsOjAsaG90ZWw6MC4yNSxyZXRhaWw6MH0sCiAgJ+yehOuMgO2Yleq4sOyImeyCrCvsmKTtlLzsiqTthZQr6re87IOdJzp7ZG9ybTowLjc1LG9mZmljZXRlbDowLjE1LGhvdGVsOjAscmV0YWlsOjAuMX0KfTsKCmNvbnN0IHRvS2V5PW49PnsKICBpZighbilyZXR1cm4gbnVsbDsKICBjb25zdCBtPXsn7KCcMeyiheyghOyaqeyjvOqxsOyngOyXrSc6J+ydvOuwmOyjvOqxsOyngOyXrV8y7KKFJywn7KCcMuyiheyghOyaqeyjvOqxsOyngOyXrSc6J+ydvOuwmOyjvOqxsOyngOyXrV8y7KKFJywn7KCcMeyiheydvOuwmOyjvOqxsOyngOyXrSc6J+ydvOuwmOyjvOqxsOyngOyXrV8y7KKFJywn7KCcMuyiheydvOuwmOyjvOqxsOyngOyXrSc6J+ydvOuwmOyjvOqxsOyngOyXrV8y7KKFJywn7KCcM+yiheydvOuwmOyjvOqxsOyngOyXrSc6J+ydvOuwmOyjvOqxsOyngOyXrV8z7KKFJywn7KSA7KO86rGw7KeA7JetJzon7KSA7KO86rGw7KeA7JetJywn7KSR7Ius7IOB7JeF7KeA7JetJzon7J2867CY7IOB7JeF7KeA7JetJywn7J2867CY7IOB7JeF7KeA7JetJzon7J2867CY7IOB7JeF7KeA7JetJywn6re866aw7IOB7JeF7KeA7JetJzon7J2867CY7IOB7JeF7KeA7JetJywn7Jyg7Ya17IOB7JeF7KeA7JetJzon7J2867CY7IOB7JeF7KeA7JetJ307CiAgZm9yKGNvbnN0IFtrLHZdIG9mIE9iamVjdC5lbnRyaWVzKG0pKWlmKG4uaW5jbHVkZXMoaykpcmV0dXJuIHY7CiAgaWYoWk9ORVNbbl0pcmV0dXJuIG47CiAgcmV0dXJuIG51bGw7Cn07Cgpjb25zdCBmbXQ9KG4sZD0wKT0+bj9uLnRvRml4ZWQoZCkucmVwbGFjZSgvXFxCKD89KFxcZHszfSkrKD8hXFxkKSkvZywnLCcpOictJzsKCmZ1bmN0aW9uIEFwcCgpewogIGNvbnN0IFtpbnB1dHMsc2V0SW5wdXRzXT11c2VTdGF0ZSh7CiAgICBsb2NhdGlvbjon7ISc7Jq47Yq567OE7IucIOyEseuPmeq1rCDrj4TshKDrj5kgMzktMicsCiAgICB6b25lVHlwZTon7J2867CY7KO86rGw7KeA7JetXzPsooUnLAogICAgbGFuZEFyZWE6Mjg0NS4zLAogICAgdXNlVHlwZTon7J6E64yA7ZiV6riw7IiZ7IKsJywKICAgIGRvcm1BcmVhOjE0LjUsCiAgICBvZmZpY2V0ZWxBcmVhOjE3LjUsCiAgICBob3RlbEFyZWE6MTcuNSwKICAgIG11bHRpWm9uZTpmYWxzZSwKICAgIGN1c3RvbUZBUjowCiAgfSk7CiAgCiAgLy8g67O17ZWpIOyaqeuPhOyngOyXrSAo64+Z7KCBIOuwsOyXtCkKICBjb25zdCBbem9uZXMsc2V0Wm9uZXNdPXVzZVN0YXRlKFsKICAgIHtpZDoxLHR5cGU6J+ydvOuwmOyjvOqxsOyngOyXrV8z7KKFJyxhcmVhOjE1MDB9LAogICAge2lkOjIsdHlwZTon7J2867CY7KO86rGw7KeA7JetXzLsooUnLGFyZWE6MTM0NS4zfQogIF0pOwogIAogIGNvbnN0IFthc3N1bXB0aW9ucyxzZXRBc3N1bXB0aW9uc109dXNlU3RhdGUoewogICAgZ3JvdW5kU2hhcmVkUmF0aW86MC41LAogICAgZG9ybUV4Y2x1c2l2ZVJhdGlvOjAuNTUsCiAgICBob3RlbE9mZmljZXRlbEV4Y2x1c2l2ZVJhdGlvOjAuNiwKICAgIG1lY2hFbGVjUmF0aW86MC4wOCwKICAgIHVuZGVyZ3JvdW5kQ292ZXJhZ2U6MC43NSwKICAgIHR5cGljYWxDb3ZlcmFnZTowLjMsCiAgICBzZWxmUGFya2luZ1JhdGlvOjAuMDMKICB9KTsKICAKICBjb25zdCBbcmVzdWx0cyxzZXRSZXN1bHRzXT11c2VTdGF0ZShudWxsKTsKICBjb25zdCBbYnVzeSxzZXRCdXN5XT11c2VTdGF0ZShmYWxzZSk7CiAgY29uc3QgW3N0LHNldFN0XT11c2VTdGF0ZShudWxsKTsKICBjb25zdCBbcmF3LHNldFJhd109dXNlU3RhdGUoJycpOwogIAogIGNvbnN0IG1zZz0odGV4dCx0eXBlLG1zPTgwMDApPT57c2V0U3Qoe3RleHQsdHlwZX0pO2lmKG1zKXNldFRpbWVvdXQoKCk9PnNldFN0KG51bGwpLG1zKTt9OwogIGNvbnN0IHVwZD0oayx2KT0+c2V0SW5wdXRzKHA9Pih7Li4ucCxba106dn0pKTsKICBjb25zdCB1cGRBc3M9KGssdik9PnNldEFzc3VtcHRpb25zKHA9Pih7Li4ucCxba106dn0pKTsKICAKICAvLyDsp4Dsl60g7LaU6rCAL+yCreygnAogIGNvbnN0IGFkZFpvbmU9KCk9PnsKICAgIGNvbnN0IG5ld0lkPU1hdGgubWF4KC4uLnpvbmVzLm1hcCh6PT56LmlkKSkrMTsKICAgIHNldFpvbmVzKFsuLi56b25lcyx7aWQ6bmV3SWQsdHlwZTon7J2867CY7KO86rGw7KeA7JetXzPsooUnLGFyZWE6MH1dKTsKICB9OwogIAogIGNvbnN0IHJlbW92ZVpvbmU9KGlkKT0+ewogICAgaWYoem9uZXMubGVuZ3RoPD0yKXJldHVybjsKICAgIHNldFpvbmVzKHpvbmVzLmZpbHRlcih6PT56LmlkIT09aWQpKTsKICB9OwogIAogIGNvbnN0IHVwZGF0ZVpvbmU9KGlkLGZpZWxkLHZhbCk9PnsKICAgIHNldFpvbmVzKHpvbmVzLm1hcCh6PT56LmlkPT09aWQ/ey4uLnosW2ZpZWxkXTp2YWx9OnopKTsKICB9OwogIAogIC8vIOyaqeyggeuloC/qsbTtj5DsnKgg6rOE7IKwCiAgY29uc3QgZ2V0Wm9uZUluZm89KCk9PnsKICAgIGlmKGlucHV0cy5tdWx0aVpvbmUpewogICAgICBjb25zdCB0b3RhbD16b25lcy5yZWR1Y2UoKHMseik9PnMrei5hcmVhLDApOwogICAgICBpZihpbnB1dHMuY3VzdG9tRkFSPjApewogICAgICAgIHJldHVybiB7YXBwbGllZEZBUjppbnB1dHMuY3VzdG9tRkFSLGFwcGxpZWRDb3ZlcmFnZTowLjQsaXNDdXN0b206dHJ1ZX07CiAgICAgIH1lbHNlIGlmKHRvdGFsPjAmJnpvbmVzLmV2ZXJ5KHo9PnouYXJlYT4wKSl7CiAgICAgICAgbGV0IGZhclN1bT0wLGNvdlN1bT0wOwogICAgICAgIHpvbmVzLmZvckVhY2goej0+ewogICAgICAgICAgY29uc3QgemQ9Wk9ORVNbei50eXBlXTsKICAgICAgICAgIGlmKHpkKXsKICAgICAgICAgICAgZmFyU3VtKz16ZC5hcHBsaWVkRkFSKnouYXJlYTsKICAgICAgICAgICAgY292U3VtKz16ZC5hcHBsaWVkQ292ZXJhZ2Uqei5hcmVhOwogICAgICAgICAgfQogICAgICAgIH0pOwogICAgICAgIHJldHVybiB7YXBwbGllZEZBUjpmYXJTdW0vdG90YWwsYXBwbGllZENvdmVyYWdlOmNvdlN1bS90b3RhbCxpc1dlaWdodGVkOnRydWUsem9uZXN9OwogICAgICB9CiAgICAgIHJldHVybiB7YXBwbGllZEZBUjozLjAsYXBwbGllZENvdmVyYWdlOjAuNH07CiAgICB9CiAgICByZXR1cm4gWk9ORVNbaW5wdXRzLnpvbmVUeXBlXXx8e2FwcGxpZWRGQVI6My4wLGFwcGxpZWRDb3ZlcmFnZTowLjR9OwogIH07CiAgCiAgY29uc3Qgem9uZUluZm89Z2V0Wm9uZUluZm8oKTsKICAKICBjb25zdCBuYXZlcj0oKT0+ewogICAgaWYoIWlucHV0cy5sb2NhdGlvbi50cmltKCkpcmV0dXJuOwogICAgd2luZG93Lm9wZW4oJ2h0dHBzOi8vbWFwLm5hdmVyLmNvbS9wL3NlYXJjaC8nK2VuY29kZVVSSUNvbXBvbmVudChpbnB1dHMubG9jYXRpb24pLCdfYmxhbmsnKTsKICB9OwogIAogIGNvbnN0IHNlYXJjaD1hc3luYygpPT57CiAgICBjb25zdCBhZGRyPWlucHV0cy5sb2NhdGlvbi50cmltKCk7CiAgICBpZighYWRkcil7bXNnKCfso7zshozrpbwg7J6F66Cl7ZW07KO87IS47JqUJywndycpO3JldHVybjt9CiAgICBzZXRCdXN5KHRydWUpO3NldFJhdygnJyk7bXNnKCfwn5SNIOyaqeuPhOyngOyXrSDsobDtmowg7KSRLi4uJywnaScsMCk7CiAgICB0cnl7CiAgICAgIGNvbnN0IHJlcz1hd2FpdCBmZXRjaCgnL3NlYXJjaCcse21ldGhvZDonUE9TVCcsaGVhZGVyczp7J0NvbnRlbnQtVHlwZSc6J2FwcGxpY2F0aW9uL2pzb24nfSxib2R5OkpTT04uc3RyaW5naWZ5KHthZGRyZXNzOmFkZHJ9KX0pOwogICAgICBpZighcmVzLm9rKXRocm93IG5ldyBFcnJvcign7ISc67KEIOyYpOulmCAnK3Jlcy5zdGF0dXMpOwogICAgICBjb25zdCBkPWF3YWl0IHJlcy5qc29uKCk7CiAgICAgICAgY29uc29sZS5sb2coJ/CflI0gQVBJIOydkeuLtTonLCBkKTsKICAgICAgaWYoZC5maW5hbCl7CiAgICAgICAgY29uc29sZS5sb2coJ+KchSDsmqnrj4Tsp4Dsl60g7KGw7ZqMIOyEseqztTonLCBkLmZpbmFsKTsKICAgICAgICBzZXRSYXcoZC5maW5hbCk7CiAgICAgICAgCiAgICAgICAgLy8g7Jes65+sIOyaqeuPhOyngOyXrSDsspjrpqwKICAgICAgICBjb25zdCB6b25lcyA9IGQuZmluYWwuc3BsaXQoJywnKS5tYXAoej0+ei50cmltKCkpOwogICAgICAgIGNvbnNvbGUubG9nKCfwn5ONIOyhsO2ajOuQnCDsmqnrj4Tsp4Dsl60g6rCc7IiYOicsIHpvbmVzLmxlbmd0aCk7CiAgICAgICAgCiAgICAgICAgaWYoem9uZXMubGVuZ3RoID4gMSl7CiAgICAgICAgICAvLyDsl6zrn6wg7Jqp64+E7KeA7Jet7J20IOyeiOydhCDrlYwKICAgICAgICAgIGNvbnN0IG1hcHBlZFpvbmVzID0gem9uZXMubWFwKHo9Pih7b3JpZ2luYWw6eixrZXk6dG9LZXkoeil9KSkuZmlsdGVyKHo9Pnoua2V5KTsKICAgICAgICAgIGNvbnNvbGUubG9nKCfwn5SEIOunpO2VkSDqsIDriqXtlZwg7Jqp64+E7KeA7JetOicsIG1hcHBlZFpvbmVzKTsKICAgICAgICAgIAogICAgICAgICAgaWYobWFwcGVkWm9uZXMubGVuZ3RoID4gMCl7CiAgICAgICAgICAgIGNvbnN0IGZpcnN0Wm9uZSA9IG1hcHBlZFpvbmVzWzBdOwogICAgICAgICAgICBjb25zb2xlLmxvZygn4pyoIOyyqyDrsojsp7gg7Jqp64+E7KeA7JetIOyekOuPmSDshKTsoJU6JywgZmlyc3Rab25lLmtleSk7CiAgICAgICAgICAgIHVwZCgnem9uZVR5cGUnLGZpcnN0Wm9uZS5rZXkpOwogICAgICAgICAgICBtc2coJ+KchSDsnpDrj5kg7KCB7JqpOiAnK2ZpcnN0Wm9uZS5vcmlnaW5hbCsnIOKGkiAnK2ZpcnN0Wm9uZS5rZXkrJ1xu8J+SoSDstJ0gJyt6b25lcy5sZW5ndGgrJ+qwnCDsmqnrj4Tsp4Dsl60g7KGw7ZqM65CoICjtlYTsp4DqsIAg6rK96rOE7JeQIOqxuOyzkOyeiOydjCknLCdvaycsMTIwMDApOwogICAgICAgICAgfWVsc2V7CiAgICAgICAgICAgIG1zZygn4pqg77iPIOyhsO2ajOuQqDogJytkLmZpbmFsKycg4oCUIOyVhOuemOyXkOyEnCDsp4HsoJEg7ISg7YOd7ZWY7IS47JqUJywndycpOwogICAgICAgICAgfQogICAgICAgIH1lbHNlewogICAgICAgICAgLy8g64uo7J28IOyaqeuPhOyngOyXrQogICAgICAgICAgY29uc3Qgaz10b0tleShkLmZpbmFsKTsKICAgICAgICAgIGNvbnNvbGUubG9nKCfwn5SEIOunpO2VkSDqsrDqs7w6JywgZC5maW5hbCwgJ+KGkicsIGspOwogICAgICAgICAgaWYoayl7CiAgICAgICAgICAgIGNvbnNvbGUubG9nKCfinKgg7J6Q64+ZIOyEpOyglSDsi6Ttlok6Jywgayk7CiAgICAgICAgICAgIHVwZCgnem9uZVR5cGUnLGspOwogICAgICAgICAgICBtc2coJ+KchSDsnpDrj5kg7KCB7JqpOiAnK2QuZmluYWwrJyDihpIgJytrLCdvaycpOwogICAgICAgICAgfWVsc2V7CiAgICAgICAgICAgIG1zZygn4pqg77iPIOyhsO2ajOuQqDogJytkLmZpbmFsKycg4oCUIOyVhOuemOyXkOyEnCDsp4HsoJEg7ISg7YOd7ZWY7IS47JqUJywndycpOwogICAgICAgICAgfQogICAgICAgIH0KICAgICAgfWVsc2V7bXNnKCfinYwg7Jqp64+E7KeA7Jet7J2EIOywvuydhCDsiJgg7JeG7Iq164uI64ukJywnZXJyJyk7fQogICAgfWNhdGNoKGUpe21zZygn4p2MIOyYpOulmDogJytlLm1lc3NhZ2UsJ2VycicpO30KICAgIGZpbmFsbHl7c2V0QnVzeShmYWxzZSk7fQogIH07CiAgCiAgY29uc3QgY2FsYz0oKT0+ewogICAgdHJ5ewogICAgICBjb25zdCByYXRpb3M9VVNFX1RZUEVTW2lucHV0cy51c2VUeXBlXTsKICAgICAgaWYoIXJhdGlvcylyZXR1cm47CiAgICAgIAogICAgICBjb25zdCBsYW5kPWlucHV0cy5sYW5kQXJlYTsKICAgICAgY29uc3QgYXBwbGllZEZBUj16b25lSW5mby5hcHBsaWVkRkFSOwogICAgICBjb25zdCBmYXJBcmVhPWxhbmQqYXBwbGllZEZBUjsKICAgICAgCiAgICAgIGNvbnN0IGRvcm1GYWM9cmF0aW9zLmRvcm0qZmFyQXJlYTsKICAgICAgY29uc3Qgb2ZmRmFjPXJhdGlvcy5vZmZpY2V0ZWwqZmFyQXJlYTsKICAgICAgY29uc3QgaG90RmFjPXJhdGlvcy5ob3RlbCpmYXJBcmVhOwogICAgICBjb25zdCByZXRGYWM9cmF0aW9zLnJldGFpbCpmYXJBcmVhOwogICAgICAKICAgICAgbGV0IGRvcm1VPTAsb2ZmVT0wLGhvdFU9MCx0b3RQPTA7CiAgICAgIGxldCBkb3JtRz1kb3JtRmFjLG9mZkc9b2ZmRmFjLGhvdEc9aG90RmFjLHJldEc9cmV0RmFjLHRvdEc9ZG9ybUcrb2ZmRytob3RHK3JldEc7CiAgICAgIGxldCBzaGFyZWQ9MCxzaGFyZWRHPTA7CiAgICAgIGxldCBkb3JtVW49MCxvZmZVbj0wLGhvdFVuPTAscmV0VW49MCx0b3RVbj0wOwogICAgICBsZXQgZG9ybVBUPTAsb2ZmUFQ9MCxob3RQVD0wLHJldFBUPTA7CiAgICAgIGxldCBkb3JtVVM9MCxvZmZVUz0wLGhvdFVTPTAscmV0VVM9MDsKICAgICAgbGV0IGRvcm1TVT0wLG9mZlNVPTAsaG90U1U9MCxyZXRTVT0wOwogICAgICBsZXQgZG9ybU1FPTAsb2ZmTUU9MCxob3RNRT0wLHJldE1FPTA7CiAgICAgIGxldCB1blNoYXJlZD0wLG1lY2hFbGVjPTA7CiAgICAgIAogICAgICBmb3IobGV0IGk9MDtpPDUwO2krKyl7CiAgICAgICAgY29uc3QgcFA9dG90UCxwRD1kb3JtVSxwTz1vZmZVLHBIPWhvdFU7CiAgICAgICAgY29uc3QgdG90VT1kb3JtVStvZmZVK2hvdFU7CiAgICAgICAgaWYodG90VTw9MTUwKXNoYXJlZD10b3RVKjQ7CiAgICAgICAgZWxzZSBpZih0b3RVPD0zMDApc2hhcmVkPTYwMCsodG90VS0xNTApKjY7CiAgICAgICAgZWxzZSBpZih0b3RVPD01MDApc2hhcmVkPTExMjUrKHRvdFUtMzAwKSo2OwogICAgICAgIGVsc2Ugc2hhcmVkPTE3MjUrKHRvdFUtNTAwKSo2OwogICAgICAgIAogICAgICAgIHNoYXJlZEc9c2hhcmVkKmFzc3VtcHRpb25zLmdyb3VuZFNoYXJlZFJhdGlvOwogICAgICAgIGNvbnN0IHNoYXJlZFVuPXNoYXJlZC1zaGFyZWRHOwogICAgICAgIAogICAgICAgIHVuU2hhcmVkPXRvdEcqMC4wMjsKICAgICAgICBtZWNoRWxlYz10b3RHKmFzc3VtcHRpb25zLm1lY2hFbGVjUmF0aW87CiAgICAgICAgCiAgICAgICAgaWYodG90Rz4wKXsKICAgICAgICAgIGRvcm1VUz11blNoYXJlZCooZG9ybUcvdG90Ryk7CiAgICAgICAgICBvZmZVUz11blNoYXJlZCoob2ZmRy90b3RHKTsKICAgICAgICAgIGhvdFVTPXVuU2hhcmVkKihob3RHL3RvdEcpOwogICAgICAgICAgcmV0VVM9dW5TaGFyZWQqKHJldEcvdG90Ryk7CiAgICAgICAgICAKICAgICAgICAgIGRvcm1TVT1zaGFyZWRVbiooZG9ybUcvdG90Ryk7CiAgICAgICAgICBvZmZTVT1zaGFyZWRVbioob2ZmRy90b3RHKTsKICAgICAgICAgIGhvdFNVPXNoYXJlZFVuKihob3RHL3RvdEcpOwogICAgICAgICAgcmV0U1U9c2hhcmVkVW4qKHJldEcvdG90Ryk7CiAgICAgICAgICAKICAgICAgICAgIGRvcm1NRT1tZWNoRWxlYyooZG9ybUcvdG90Ryk7CiAgICAgICAgICBvZmZNRT1tZWNoRWxlYyoob2ZmRy90b3RHKTsKICAgICAgICAgIGhvdE1FPW1lY2hFbGVjKihob3RHL3RvdEcpOwogICAgICAgICAgcmV0TUU9bWVjaEVsZWMqKHJldEcvdG90Ryk7CiAgICAgICAgICAKICAgICAgICAgIGRvcm1Vbj1kb3JtVVMrZG9ybVNVK2Rvcm1NRTsKICAgICAgICAgIG9mZlVuPW9mZlVTK29mZlNVK29mZk1FOwogICAgICAgICAgaG90VW49aG90VVMraG90U1UraG90TUU7CiAgICAgICAgICByZXRVbj1yZXRVUytyZXRTVStyZXRNRTsKICAgICAgICB9CiAgICAgICAgCiAgICAgICAgdG90VW49ZG9ybVVuK29mZlVuK2hvdFVuK3JldFVuOwogICAgICAgIAogICAgICAgIGNvbnN0IGRvcm1QPXJhdGlvcy5kb3JtPjA/TWF0aC5jZWlsKChkb3JtRytkb3JtVW4pLzIwMCk6MDsKICAgICAgICBjb25zdCBvZmZQPXJhdGlvcy5vZmZpY2V0ZWw+MD9NYXRoLmZsb29yKG9mZlUqMC41KTowOwogICAgICAgIGNvbnN0IGhvdFA9cmF0aW9zLmhvdGVsPjA/TWF0aC5jZWlsKChob3RHK2hvdFVuKS8xMzQpOjA7CiAgICAgICAgY29uc3QgcmV0UD1yYXRpb3MucmV0YWlsPjA/TWF0aC5jZWlsKChyZXRHK3JldFVuKS8xMzQpOjA7CiAgICAgICAgdG90UD1kb3JtUCtvZmZQK2hvdFArcmV0UDsKICAgICAgICAKICAgICAgICBjb25zdCBzZWxmUD1NYXRoLmNlaWwodG90UCphc3N1bXB0aW9ucy5zZWxmUGFya2luZ1JhdGlvKTsKICAgICAgICBjb25zdCBtZWNoUD10b3RQLXNlbGZQOwogICAgICAgIGNvbnN0IHB0VW5pdHM9TWF0aC5jZWlsKG1lY2hQLzgwKTsKICAgICAgICBjb25zdCBwdFRvdGFsPXB0VW5pdHMqNTA7CiAgICAgICAgCiAgICAgICAgY29uc3QgZmFjU3VtPWRvcm1GYWMrb2ZmRmFjK2hvdEZhYytyZXRGYWM7CiAgICAgICAgaWYoZmFjU3VtPjApewogICAgICAgICAgZG9ybVBUPXB0VG90YWwqKGRvcm1GYWMvZmFjU3VtKTsKICAgICAgICAgIG9mZlBUPXB0VG90YWwqKG9mZkZhYy9mYWNTdW0pOwogICAgICAgICAgaG90UFQ9cHRUb3RhbCooaG90RmFjL2ZhY1N1bSk7CiAgICAgICAgICByZXRQVD1wdFRvdGFsKihyZXRGYWMvZmFjU3VtKTsKICAgICAgICAgIAogICAgICAgICAgZG9ybUc9ZG9ybUZhYytkb3JtUFQ7CiAgICAgICAgICBvZmZHPW9mZkZhYytvZmZQVDsKICAgICAgICAgIGhvdEc9aG90RmFjK2hvdFBUOwogICAgICAgICAgcmV0Rz1yZXRGYWMrcmV0UFQ7CiAgICAgICAgfQogICAgICAgIAogICAgICAgIHRvdEc9ZG9ybUcrb2ZmRytob3RHK3JldEc7CiAgICAgICAgCiAgICAgICAgaWYoZG9ybUc+MClkb3JtVT1NYXRoLmZsb29yKChkb3JtRy1zaGFyZWRHKSphc3N1bXB0aW9ucy5kb3JtRXhjbHVzaXZlUmF0aW8vaW5wdXRzLmRvcm1BcmVhKTsKICAgICAgICAKICAgICAgICBpZihvZmZHPjApewogICAgICAgICAgY29uc3Qgb2ZmU0c9cmF0aW9zLmRvcm0+MD8wOihzaGFyZWRHKihvZmZHL3RvdEcpKTsKICAgICAgICAgIG9mZlU9TWF0aC5mbG9vcigob2ZmRy1vZmZTRykqYXNzdW1wdGlvbnMuaG90ZWxPZmZpY2V0ZWxFeGNsdXNpdmVSYXRpby9pbnB1dHMub2ZmaWNldGVsQXJlYSk7CiAgICAgICAgfQogICAgICAgIAogICAgICAgIGlmKGhvdEc+MCl7CiAgICAgICAgICBjb25zdCBob3RTRz1yYXRpb3MuZG9ybT4wPzA6KHNoYXJlZEcqKGhvdEcvdG90RykpOwogICAgICAgICAgaG90VT1NYXRoLmZsb29yKChob3RHLWhvdFNHKSphc3N1bXB0aW9ucy5ob3RlbE9mZmljZXRlbEV4Y2x1c2l2ZVJhdGlvL2lucHV0cy5ob3RlbEFyZWEpOwogICAgICAgIH0KICAgICAgICAKICAgICAgICBpZihNYXRoLmFicyh0b3RQLXBQKTwxJiZkb3JtVT09PXBEJiZvZmZVPT09cE8mJmhvdFU9PT1wSClicmVhazsKICAgICAgfQogICAgICAKICAgICAgY29uc3QgdG90VT1kb3JtVStvZmZVK2hvdFU7CiAgICAgIGNvbnN0IGdGbG9vcnM9TWF0aC5jZWlsKHRvdEcvKGxhbmQqYXNzdW1wdGlvbnMudHlwaWNhbENvdmVyYWdlKSkrMTsKICAgICAgY29uc3QgdUZsb29ycz1NYXRoLmNlaWwodG90VW4vKGxhbmQqYXNzdW1wdGlvbnMudW5kZXJncm91bmRDb3ZlcmFnZSkpOwogICAgICBjb25zdCBoZWlnaHQ9Z0Zsb29ycyozLjM7CiAgICAgIGNvbnN0IGNvbnN0UGVyaW9kPWdGbG9vcnMrKHVGbG9vcnMqMykrNjsKICAgICAgY29uc3QgZGV2UGVyaW9kPTE1K2NvbnN0UGVyaW9kOwogICAgICAKICAgICAgc2V0UmVzdWx0cyh7CiAgICAgICAgdG90YWxVbml0czp0b3RVLAogICAgICAgIGJ1aWxkaW5nSGVpZ2h0OmhlaWdodCwKICAgICAgICBncm91bmRGbG9vcnM6Z0Zsb29ycywKICAgICAgICB1bmRlcmdyb3VuZEZsb29yczp1Rmxvb3JzLAogICAgICAgIGRldlBlcmlvZCwKICAgICAgICBjb25zdFBlcmlvZCwKICAgICAgICBmYWNpbGl0eURhdGE6ewogICAgICAgICAgcmF0aW9zLAogICAgICAgICAgZG9ybTp7Z3JvdW5kOmRvcm1HLGZhY2lsaXR5QXJlYTpkb3JtRmFjLHBhcmtpbmdUb3dlcjpkb3JtUFQsdW5kZXI6ZG9ybVVuLHVuZGVyU2hhcmVkOmRvcm1VUyxwYXJraW5nTG90OmRvcm1Vbi1kb3JtVVMtZG9ybVNVLWRvcm1NRSxzaGFyZWRVbmRlcjpkb3JtU1UsbWVjaEVsZWM6ZG9ybU1FLHRvdGFsOmRvcm1HK2Rvcm1Vbix1bml0czpkb3JtVSxwYXJraW5nOnJhdGlvcy5kb3JtPjA/TWF0aC5jZWlsKChkb3JtRytkb3JtVW4pLzIwMCk6MH0sCiAgICAgICAgICBvZmZpY2V0ZWw6e2dyb3VuZDpvZmZHLGZhY2lsaXR5QXJlYTpvZmZGYWMscGFya2luZ1Rvd2VyOm9mZlBULHVuZGVyOm9mZlVuLHVuZGVyU2hhcmVkOm9mZlVTLHBhcmtpbmdMb3Q6b2ZmVW4tb2ZmVVMtb2ZmU1Utb2ZmTUUsc2hhcmVkVW5kZXI6b2ZmU1UsbWVjaEVsZWM6b2ZmTUUsdG90YWw6b2ZmRytvZmZVbix1bml0czpvZmZVLHBhcmtpbmc6cmF0aW9zLm9mZmljZXRlbD4wP01hdGguZmxvb3Iob2ZmVSowLjUpOjB9LAogICAgICAgICAgaG90ZWw6e2dyb3VuZDpob3RHLGZhY2lsaXR5QXJlYTpob3RGYWMscGFya2luZ1Rvd2VyOmhvdFBULHVuZGVyOmhvdFVuLHVuZGVyU2hhcmVkOmhvdFVTLHBhcmtpbmdMb3Q6aG90VW4taG90VVMtaG90U1UtaG90TUUsc2hhcmVkVW5kZXI6aG90U1UsbWVjaEVsZWM6aG90TUUsdG90YWw6aG90Rytob3RVbix1bml0czpob3RVLHBhcmtpbmc6cmF0aW9zLmhvdGVsPjA/TWF0aC5jZWlsKChob3RHK2hvdFVuKS8xMzQpOjB9LAogICAgICAgICAgcmV0YWlsOntncm91bmQ6cmV0RyxmYWNpbGl0eUFyZWE6cmV0RmFjLHBhcmtpbmdUb3dlcjpyZXRQVCx1bmRlcjpyZXRVbix1bmRlclNoYXJlZDpyZXRVUyxwYXJraW5nTG90OnJldFVuLXJldFVTLXJldFNVLXJldE1FLHNoYXJlZFVuZGVyOnJldFNVLG1lY2hFbGVjOnJldE1FLHRvdGFsOnJldEcrcmV0VW4scGFya2luZzpyYXRpb3MucmV0YWlsPjA/TWF0aC5jZWlsKChyZXRHK3JldFVuKS8xMzQpOjB9LAogICAgICAgICAgdG90YWxzOntncm91bmQ6dG90RyxmYWNpbGl0eUFyZWE6ZG9ybUZhYytvZmZGYWMraG90RmFjK3JldEZhYyxwYXJraW5nVG93ZXI6ZG9ybVBUK29mZlBUK2hvdFBUK3JldFBULHVuZGVyOnRvdFVuLHVuZGVyU2hhcmVkOnVuU2hhcmVkLHBhcmtpbmdMb3Q6dG90VW4tdW5TaGFyZWQtKHNoYXJlZC1zaGFyZWRHKS1tZWNoRWxlYyxzaGFyZWRVbmRlcjpzaGFyZWQtc2hhcmVkRyxtZWNoRWxlYzptZWNoRWxlYyx0b3RhbDp0b3RHK3RvdFVuLHVuaXRzOnRvdFUscGFya2luZzp0b3RQLHNoYXJlZFNwYWNlOnNoYXJlZCxzaGFyZWRTcGFjZUdyb3VuZDpzaGFyZWRHLHNoYXJlZFNwYWNlVW5kZXI6c2hhcmVkLXNoYXJlZEd9CiAgICAgICAgfQogICAgICB9KTsKICAgIH1jYXRjaChlKXtjb25zb2xlLmVycm9yKCfqs4TsgrAg7Jik66WYOicsZSk7fQogIH07CiAgCiAgdXNlRWZmZWN0KCgpPT57Y2FsYygpO30sW2lucHV0cyxhc3N1bXB0aW9ucyx6b25lc10pOwogIAogIGNvbnN0IHNjPXN0P3tpOidzdC1pJyxvazonc3Qtb2snLGVycjonc3QtZXJyJyx3OidzdC13YXJuJ31bc3QudHlwZV06Jyc7CiAgY29uc3QgZmFjPXJlc3VsdHM/LmZhY2lsaXR5RGF0YTsKICAKICByZXR1cm4gKAogICAgPGRpdiBjbGFzc05hbWU9ImNvbnRhaW5lciI+CiAgICAgIDxkaXYgY2xhc3NOYW1lPSJoZWFkZXIiPgogICAgICAgIDxoMT7wn4+X77iPIOyVveyLnSDqt5zrqqjqsoDthqAg6rOE7IKw6riwPC9oMT4KICAgICAgICA8cD7ruaDrpbgg7IKs7JeF7ISxIO2MkOuLqOydhCDsnITtlZwg64+E6rWsPC9wPgogICAgICA8L2Rpdj4KICAgICAgCiAgICAgIDxkaXYgY2xhc3NOYW1lPSJjb250ZW50Ij4KICAgICAgICAKICAgICAgICA8ZGl2IGNsYXNzTmFtZT0ic2VjdGlvbiI+CiAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0ic2VjdGlvbi10aXRsZSI+8J+TjSDrjIDsp4DsnITsuZg8L2Rpdj4KICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJmaWVsZCI+CiAgICAgICAgICAgIDxsYWJlbD7so7zshow8L2xhYmVsPgogICAgICAgICAgICA8aW5wdXQgdHlwZT0idGV4dCIgdmFsdWU9e2lucHV0cy5sb2NhdGlvbn0gb25DaGFuZ2U9e2U9PnVwZCgnbG9jYXRpb24nLGUudGFyZ2V0LnZhbHVlKX0gb25LZXlEb3duPXtlPT5lLmtleT09PSdFbnRlcicmJnNlYXJjaCgpfSBwbGFjZWhvbGRlcj0i7JiIOiDshJzsmrjtirnrs4Tsi5wg6rCV64Ko6rWsIOyXreyCvOuPmSAxMjMtNDUiLz4KICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImJ0bi1yb3ciPgogICAgICAgICAgICAgIDxidXR0b24gY2xhc3NOYW1lPSJidG4gYnRuLWJsdWUiIG9uQ2xpY2s9e3NlYXJjaH0gZGlzYWJsZWQ9e2J1c3l9PgogICAgICAgICAgICAgICAge2J1c3k/J+KPsyDsobDtmowg7KSRLi4uJzon8J+UjSDsmqnrj4Tsp4Dsl60g7J6Q64+Z6rKA7IOJJ30KICAgICAgICAgICAgICA8L2J1dHRvbj4KICAgICAgICAgICAgICA8YnV0dG9uIGNsYXNzTmFtZT0iYnRuIGJ0bi1ncmVlbiIgb25DbGljaz17bmF2ZXJ9PvCfl7rvuI8g64Sk7J2067KEPC9idXR0b24+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICB7c3QmJjxkaXYgY2xhc3NOYW1lPXsnc3RhdHVzICcrc2N9PntzdC50ZXh0fTwvZGl2Pn0KICAgICAgICAgICAge3JhdyYmPGRpdiBjbGFzc05hbWU9InJhdyI+8J+TjSDsobDtmozrkJwg7Jqp64+E7KeA7JetOiA8c3Ryb25nPntyYXd9PC9zdHJvbmc+PC9kaXY+fQogICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgICAgCiAgICAgICAgPGRpdiBjbGFzc05hbWU9InNlY3Rpb24iPgogICAgICAgICAgPGRpdiBjbGFzc05hbWU9InNlY3Rpb24tdGl0bGUiPvCfk4og6riw67O4IOygleuztDwvZGl2PgogICAgICAgICAgCiAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iZmllbGQiIHN0eWxlPXt7bWFyZ2luQm90dG9tOicxNnB4J319PgogICAgICAgICAgICA8bGFiZWw+CiAgICAgICAgICAgICAgPGlucHV0IHR5cGU9ImNoZWNrYm94IiBjaGVja2VkPXtpbnB1dHMubXVsdGlab25lfSBvbkNoYW5nZT17ZT0+dXBkKCdtdWx0aVpvbmUnLGUudGFyZ2V0LmNoZWNrZWQpfSBzdHlsZT17e21hcmdpblJpZ2h0Oic4cHgnfX0vPgogICAgICAgICAgICAgIOuzte2VqSDsmqnrj4Tsp4Dsl60gKDLqsJwg7J207IOBKQogICAgICAgICAgICA8L2xhYmVsPgogICAgICAgICAgPC9kaXY+CiAgICAgICAgICAKICAgICAgICAgIHshaW5wdXRzLm11bHRpWm9uZT8oCiAgICAgICAgICAgIDw+CiAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImdyaWQgZ3JpZC0zIj4KICAgICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJmaWVsZCI+CiAgICAgICAgICAgICAgICAgIDxsYWJlbD7smqnrj4Tsp4Dsl60ge3JhdyYmPHNwYW4gY2xhc3NOYW1lPSJiYWRnZSI+4pyoIOyekOuPmSDshKTsoJXrkKg8L3NwYW4+fTwvbGFiZWw+CiAgICAgICAgICAgICAgICAgIDxzZWxlY3QgdmFsdWU9e2lucHV0cy56b25lVHlwZX0gb25DaGFuZ2U9e2U9PnVwZCgnem9uZVR5cGUnLGUudGFyZ2V0LnZhbHVlKX0+CiAgICAgICAgICAgICAgICAgICAge09iamVjdC5rZXlzKFpPTkVTKS5tYXAoaz0+PG9wdGlvbiBrZXk9e2t9IHZhbHVlPXtrfT57a308L29wdGlvbj4pfQogICAgICAgICAgICAgICAgICA8L3NlbGVjdD4KICAgICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImZpZWxkIj4KICAgICAgICAgICAgICAgICAgPGxhYmVsPuuMgOyngOuptOyggSAo446hKTwvbGFiZWw+CiAgICAgICAgICAgICAgICAgIDxpbnB1dCB0eXBlPSJudW1iZXIiIHZhbHVlPXtpbnB1dHMubGFuZEFyZWF9IG9uQ2hhbmdlPXtlPT51cGQoJ2xhbmRBcmVhJyxwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCl9Lz4KICAgICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImZpZWxkIj4KICAgICAgICAgICAgICAgICAgPGxhYmVsPuyaqeuPhDwvbGFiZWw+CiAgICAgICAgICAgICAgICAgIDxzZWxlY3QgdmFsdWU9e2lucHV0cy51c2VUeXBlfSBvbkNoYW5nZT17ZT0+dXBkKCd1c2VUeXBlJyxlLnRhcmdldC52YWx1ZSl9PgogICAgICAgICAgICAgICAgICAgIHtPYmplY3Qua2V5cyhVU0VfVFlQRVMpLm1hcChrPT48b3B0aW9uIGtleT17a30gdmFsdWU9e2t9PntrfTwvb3B0aW9uPil9CiAgICAgICAgICAgICAgICAgIDwvc2VsZWN0PgogICAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImluZm8tYm94IiBzdHlsZT17e21hcmdpblRvcDonMTZweCd9fT4KICAgICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJpbmZvLXJvdyI+CiAgICAgICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0iaW5mby1sYWJlbCI+67KV7KCVIOqxtO2PkOycqDwvc3Bhbj4KICAgICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJpbmZvLXZhbHVlIj57Zm10KHpvbmVJbmZvLmxlZ2FsQ292ZXJhZ2UqMTAwLDApfSU8L3NwYW4+CiAgICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJpbmZvLXJvdyI+CiAgICAgICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0iaW5mby1sYWJlbCI+7KCB7JqpIOqxtO2PkOycqDwvc3Bhbj4KICAgICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJpbmZvLXZhbHVlIj57Zm10KHpvbmVJbmZvLmFwcGxpZWRDb3ZlcmFnZSoxMDAsMCl9JTwvc3Bhbj4KICAgICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImluZm8tcm93Ij4KICAgICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJpbmZvLWxhYmVsIj7rspXsoJUg7Jqp7KCB66WgPC9zcGFuPgogICAgICAgICAgICAgICAgICA8c3BhbiBjbGFzc05hbWU9ImluZm8tdmFsdWUiPntmbXQoem9uZUluZm8ubGVnYWxGQVIqMTAwLDApfSU8L3NwYW4+CiAgICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJpbmZvLXJvdyI+CiAgICAgICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0iaW5mby1sYWJlbCI+7KCB7JqpIOyaqeyggeuloDwvc3Bhbj4KICAgICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJpbmZvLXZhbHVlIj57Zm10KHpvbmVJbmZvLmFwcGxpZWRGQVIqMTAwLDApfSU8L3NwYW4+CiAgICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgPC8+CiAgICAgICAgICApOigKICAgICAgICAgICAgPD4KICAgICAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iZ3JpZCBncmlkLTIiIHN0eWxlPXt7bWFyZ2luQm90dG9tOicxNnB4J319PgogICAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImZpZWxkIj4KICAgICAgICAgICAgICAgICAgPGxhYmVsPuuMgOyngOuptOyggSAo446hKTwvbGFiZWw+CiAgICAgICAgICAgICAgICAgIDxpbnB1dCB0eXBlPSJudW1iZXIiIHZhbHVlPXtpbnB1dHMubGFuZEFyZWF9IG9uQ2hhbmdlPXtlPT51cGQoJ2xhbmRBcmVhJyxwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCl9Lz4KICAgICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImZpZWxkIj4KICAgICAgICAgICAgICAgICAgPGxhYmVsPuyaqeuPhDwvbGFiZWw+CiAgICAgICAgICAgICAgICAgIDxzZWxlY3QgdmFsdWU9e2lucHV0cy51c2VUeXBlfSBvbkNoYW5nZT17ZT0+dXBkKCd1c2VUeXBlJyxlLnRhcmdldC52YWx1ZSl9PgogICAgICAgICAgICAgICAgICAgIHtPYmplY3Qua2V5cyhVU0VfVFlQRVMpLm1hcChrPT48b3B0aW9uIGtleT17a30gdmFsdWU9e2t9PntrfTwvb3B0aW9uPil9CiAgICAgICAgICAgICAgICAgIDwvc2VsZWN0PgogICAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9Im11bHRpLXpvbmUiPgogICAgICAgICAgICAgICAgPGg0PvCfk5Ag67O17ZWpIOyaqeuPhOyngOyXrSDshKTsoJU8L2g0PgogICAgICAgICAgICAgICAgCiAgICAgICAgICAgICAgICB7em9uZXMubWFwKCh6b25lLGlkeCk9PigKICAgICAgICAgICAgICAgICAgPGRpdiBrZXk9e3pvbmUuaWR9IGNsYXNzTmFtZT0iem9uZS1yb3ciPgogICAgICAgICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJsYWJlbCI+7KeA7JetIHtpZHgrMX08L2Rpdj4KICAgICAgICAgICAgICAgICAgICA8c2VsZWN0IHZhbHVlPXt6b25lLnR5cGV9IG9uQ2hhbmdlPXtlPT51cGRhdGVab25lKHpvbmUuaWQsJ3R5cGUnLGUudGFyZ2V0LnZhbHVlKX0+CiAgICAgICAgICAgICAgICAgICAgICB7T2JqZWN0LmtleXMoWk9ORVMpLm1hcChrPT48b3B0aW9uIGtleT17a30gdmFsdWU9e2t9PntrfTwvb3B0aW9uPil9CiAgICAgICAgICAgICAgICAgICAgPC9zZWxlY3Q+CiAgICAgICAgICAgICAgICAgICAgPGlucHV0IHR5cGU9Im51bWJlciIgdmFsdWU9e3pvbmUuYXJlYX0gb25DaGFuZ2U9e2U9PnVwZGF0ZVpvbmUoem9uZS5pZCwnYXJlYScscGFyc2VGbG9hdChlLnRhcmdldC52YWx1ZSl8fDApfSBwbGFjZWhvbGRlcj0i66m07KCBICjjjqEpIi8+CiAgICAgICAgICAgICAgICAgICAge3pvbmVzLmxlbmd0aD4yJiY8YnV0dG9uIGNsYXNzTmFtZT0iYnRuIGJ0bi1yZWQiIG9uQ2xpY2s9eygpPT5yZW1vdmVab25lKHpvbmUuaWQpfT7inJU8L2J1dHRvbj59CiAgICAgICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgICAgKSl9CiAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgIDxidXR0b24gY2xhc3NOYW1lPSJidG4gYnRuLWFkZCIgb25DbGljaz17YWRkWm9uZX0+4p6VIOyngOyXrSDstpTqsIA8L2J1dHRvbj4KICAgICAgICAgICAgICAgIAogICAgICAgICAgICAgICAge3pvbmVJbmZvLmlzV2VpZ2h0ZWQmJigKICAgICAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImluZm8tYm94IiBzdHlsZT17e21hcmdpblRvcDonMTZweCd9fT4KICAgICAgICAgICAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iaW5mby1yb3ciPgogICAgICAgICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJpbmZvLWxhYmVsIj7qsIDspJHtj4nqt6Ag7Jqp7KCB66WgPC9zcGFuPgogICAgICAgICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJpbmZvLXZhbHVlIj57Zm10KHpvbmVJbmZvLmFwcGxpZWRGQVIqMTAwLDEpfSU8L3NwYW4+CiAgICAgICAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAgICAgICAgPGRpdiBzdHlsZT17e2ZvbnRTaXplOicxMXB4Jyxjb2xvcjonIzNiODJmNicsbWFyZ2luVG9wOic4cHgnfX0+CiAgICAgICAgICAgICAgICAgICAgICB7em9uZXMubWFwKCh6LGkpPT57CiAgICAgICAgICAgICAgICAgICAgICAgIGNvbnN0IHpkPVpPTkVTW3oudHlwZV07CiAgICAgICAgICAgICAgICAgICAgICAgIHJldHVybiB6ZD9gJHt6LnR5cGV9ICR7Zm10KHpkLmFwcGxpZWRGQVIqMTAwLDApfSUgw5cgJHtmbXQoei5hcmVhLDApfeOOoSR7aTx6b25lcy5sZW5ndGgtMT8nICsgJzonJ31gOicnCiAgICAgICAgICAgICAgICAgICAgICB9KS5qb2luKCcnKX0gw7cge2ZtdCh6b25lcy5yZWR1Y2UoKHMseik9PnMrei5hcmVhLDApLDApfeOOoQogICAgICAgICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgICAgICl9CiAgICAgICAgICAgICAgICAKICAgICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJmaWVsZCIgc3R5bGU9e3ttYXJnaW5Ub3A6JzEycHgnfX0+CiAgICAgICAgICAgICAgICAgIDxsYWJlbD7rmJDripQg7KeB7KCRIOyeheugpSAo7Jqp7KCB66WgICUpPC9sYWJlbD4KICAgICAgICAgICAgICAgICAgPGlucHV0IHR5cGU9Im51bWJlciIgc3RlcD0iMC4wMSIgdmFsdWU9e2lucHV0cy5jdXN0b21GQVIqMTAwfSBvbkNoYW5nZT17ZT0+dXBkKCdjdXN0b21GQVInLChwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCkvMTAwKX0gcGxhY2Vob2xkZXI9IuyYiDogMjk5Ii8+CiAgICAgICAgICAgICAgICAgIHtpbnB1dHMuY3VzdG9tRkFSPjAmJjxkaXYgc3R5bGU9e3tmb250U2l6ZTonMTFweCcsY29sb3I6JyMxMGI5ODEnLG1hcmdpblRvcDonNHB4J319PuKchSDsp4HsoJEg7J6F66ClOiB7Zm10KGlucHV0cy5jdXN0b21GQVIqMTAwLDEpfSUg7KCB7Jqp65CoPC9kaXY+fQogICAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDwvPgogICAgICAgICAgKX0KICAgICAgICA8L2Rpdj4KICAgICAgICAKICAgICAgICA8ZGl2IGNsYXNzTmFtZT0ic2VjdGlvbiI+CiAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0ic2VjdGlvbi10aXRsZSI+8J+PoCDtmLjsi6Qg66m07KCBPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iZ3JpZCBncmlkLTMiPgogICAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iZmllbGQiPgogICAgICAgICAgICAgIDxsYWJlbD7snoTrjIDtmJXquLDsiJnsgqwg7Zi47Iuk66m07KCBICjjjqEpPC9sYWJlbD4KICAgICAgICAgICAgICA8aW5wdXQgdHlwZT0ibnVtYmVyIiBzdGVwPSIwLjEiIHZhbHVlPXtpbnB1dHMuZG9ybUFyZWF9IG9uQ2hhbmdlPXtlPT51cGQoJ2Rvcm1BcmVhJyxwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCl9Lz4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJmaWVsZCI+CiAgICAgICAgICAgICAgPGxhYmVsPuyYpO2UvOyKpO2FlCDtmLjsi6TrqbTsoIEgKOOOoSk8L2xhYmVsPgogICAgICAgICAgICAgIDxpbnB1dCB0eXBlPSJudW1iZXIiIHN0ZXA9IjAuMSIgdmFsdWU9e2lucHV0cy5vZmZpY2V0ZWxBcmVhfSBvbkNoYW5nZT17ZT0+dXBkKCdvZmZpY2V0ZWxBcmVhJyxwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCl9Lz4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJmaWVsZCI+CiAgICAgICAgICAgICAgPGxhYmVsPu2YuO2FlCDtmLjsi6TrqbTsoIEgKOOOoSk8L2xhYmVsPgogICAgICAgICAgICAgIDxpbnB1dCB0eXBlPSJudW1iZXIiIHN0ZXA9IjAuMSIgdmFsdWU9e2lucHV0cy5ob3RlbEFyZWF9IG9uQ2hhbmdlPXtlPT51cGQoJ2hvdGVsQXJlYScscGFyc2VGbG9hdChlLnRhcmdldC52YWx1ZSl8fDApfS8+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgPC9kaXY+CiAgICAgICAgCiAgICAgICAgPGRpdiBjbGFzc05hbWU9InNlY3Rpb24iPgogICAgICAgICAgPGRpdiBjbGFzc05hbWU9InNlY3Rpb24tdGl0bGUiPuKame+4jyDso7zsmpQg6rCA7KCVPC9kaXY+CiAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iYXNzdW1wdGlvbnMiPgogICAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iYXNzdW1wdGlvbi1pdGVtIj4KICAgICAgICAgICAgICA8bGFiZWw+MUYg6rO17Jyg6rO16rCEIOu5hOycqDwvbGFiZWw+CiAgICAgICAgICAgICAgPGlucHV0IHR5cGU9Im51bWJlciIgc3RlcD0iMC4wMSIgdmFsdWU9e2Fzc3VtcHRpb25zLmdyb3VuZFNoYXJlZFJhdGlvfSBvbkNoYW5nZT17ZT0+dXBkQXNzKCdncm91bmRTaGFyZWRSYXRpbycscGFyc2VGbG9hdChlLnRhcmdldC52YWx1ZSl8fDApfS8+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iYXNzdW1wdGlvbi1pdGVtIj4KICAgICAgICAgICAgICA8bGFiZWw+6riw7IiZ7IKsIOyghOyaqeuloDwvbGFiZWw+CiAgICAgICAgICAgICAgPGlucHV0IHR5cGU9Im51bWJlciIgc3RlcD0iMC4wMSIgdmFsdWU9e2Fzc3VtcHRpb25zLmRvcm1FeGNsdXNpdmVSYXRpb30gb25DaGFuZ2U9e2U9PnVwZEFzcygnZG9ybUV4Y2x1c2l2ZVJhdGlvJyxwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCl9Lz4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJhc3N1bXB0aW9uLWl0ZW0iPgogICAgICAgICAgICAgIDxsYWJlbD7tmLjthZQv7Jik7ZS87Iqk7YWUIOyghOyaqeuloDwvbGFiZWw+CiAgICAgICAgICAgICAgPGlucHV0IHR5cGU9Im51bWJlciIgc3RlcD0iMC4wMSIgdmFsdWU9e2Fzc3VtcHRpb25zLmhvdGVsT2ZmaWNldGVsRXhjbHVzaXZlUmF0aW99IG9uQ2hhbmdlPXtlPT51cGRBc3MoJ2hvdGVsT2ZmaWNldGVsRXhjbHVzaXZlUmF0aW8nLHBhcnNlRmxvYXQoZS50YXJnZXQudmFsdWUpfHwwKX0vPgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9ImFzc3VtcHRpb24taXRlbSI+CiAgICAgICAgICAgICAgPGxhYmVsPuq4sOqzhOyghOq4sOyLpCDruYTsnKg8L2xhYmVsPgogICAgICAgICAgICAgIDxpbnB1dCB0eXBlPSJudW1iZXIiIHN0ZXA9IjAuMDEiIHZhbHVlPXthc3N1bXB0aW9ucy5tZWNoRWxlY1JhdGlvfSBvbkNoYW5nZT17ZT0+dXBkQXNzKCdtZWNoRWxlY1JhdGlvJyxwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCl9Lz4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJhc3N1bXB0aW9uLWl0ZW0iPgogICAgICAgICAgICAgIDxsYWJlbD7sp4DtlZgg6rG07Y+Q7JyoPC9sYWJlbD4KICAgICAgICAgICAgICA8aW5wdXQgdHlwZT0ibnVtYmVyIiBzdGVwPSIwLjAxIiB2YWx1ZT17YXNzdW1wdGlvbnMudW5kZXJncm91bmRDb3ZlcmFnZX0gb25DaGFuZ2U9e2U9PnVwZEFzcygndW5kZXJncm91bmRDb3ZlcmFnZScscGFyc2VGbG9hdChlLnRhcmdldC52YWx1ZSl8fDApfS8+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iYXNzdW1wdGlvbi1pdGVtIj4KICAgICAgICAgICAgICA8bGFiZWw+6riw7KSA7Li1IOqxtO2PkOycqDwvbGFiZWw+CiAgICAgICAgICAgICAgPGlucHV0IHR5cGU9Im51bWJlciIgc3RlcD0iMC4wMSIgdmFsdWU9e2Fzc3VtcHRpb25zLnR5cGljYWxDb3ZlcmFnZX0gb25DaGFuZ2U9e2U9PnVwZEFzcygndHlwaWNhbENvdmVyYWdlJyxwYXJzZUZsb2F0KGUudGFyZ2V0LnZhbHVlKXx8MCl9Lz4KICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJhc3N1bXB0aW9uLWl0ZW0iPgogICAgICAgICAgICAgIDxsYWJlbD7snpDso7zsi50g7KO87LCoIOu5hOycqDwvbGFiZWw+CiAgICAgICAgICAgICAgPGlucHV0IHR5cGU9Im51bWJlciIgc3RlcD0iMC4wMSIgdmFsdWU9e2Fzc3VtcHRpb25zLnNlbGZQYXJraW5nUmF0aW99IG9uQ2hhbmdlPXtlPT51cGRBc3MoJ3NlbGZQYXJraW5nUmF0aW8nLHBhcnNlRmxvYXQoZS50YXJnZXQudmFsdWUpfHwwKX0vPgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgIDwvZGl2PgogICAgICAgIAogICAgICAgIHtyZXN1bHRzJiYoCiAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0icmVzdWx0cyI+CiAgICAgICAgICAgIDxoMz7wn5OIIOyCsOy2nCDqsrDqs7w8L2gzPgogICAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0iZ3JpZCBncmlkLTIiPgogICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJtZXRyaWMiPgogICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJtZXRyaWMtbGFiZWwiPuy0nSDshLjrjIDsiJg8L3NwYW4+CiAgICAgICAgICAgICAgICA8c3BhbiBjbGFzc05hbWU9Im1ldHJpYy12YWx1ZSI+e2ZtdChyZXN1bHRzLnRvdGFsVW5pdHMsMCl97IS464yAPC9zcGFuPgogICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJtZXRyaWMiPgogICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJtZXRyaWMtbGFiZWwiPuqxtOusvCDrhpLsnbQ8L3NwYW4+CiAgICAgICAgICAgICAgICA8c3BhbiBjbGFzc05hbWU9Im1ldHJpYy12YWx1ZSI+e2ZtdChyZXN1bHRzLmJ1aWxkaW5nSGVpZ2h0LDIpfW08L3NwYW4+CiAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgICAgPGRpdiBjbGFzc05hbWU9Im1ldHJpYyI+CiAgICAgICAgICAgICAgICA8c3BhbiBjbGFzc05hbWU9Im1ldHJpYy1sYWJlbCI+7KeA7IOBIOy4teyImDwvc3Bhbj4KICAgICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0ibWV0cmljLXZhbHVlIj57cmVzdWx0cy5ncm91bmRGbG9vcnN97Li1PC9zcGFuPgogICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJtZXRyaWMiPgogICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJtZXRyaWMtbGFiZWwiPuyngO2VmCDsuLXsiJg8L3NwYW4+CiAgICAgICAgICAgICAgICA8c3BhbiBjbGFzc05hbWU9Im1ldHJpYy12YWx1ZSI+e3Jlc3VsdHMudW5kZXJncm91bmRGbG9vcnN97Li1PC9zcGFuPgogICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJtZXRyaWMiPgogICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJtZXRyaWMtbGFiZWwiPuqwnOuwnOq4sOqwhDwvc3Bhbj4KICAgICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0ibWV0cmljLXZhbHVlIj57cmVzdWx0cy5kZXZQZXJpb2R96rCc7JuUPC9zcGFuPgogICAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJtZXRyaWMiPgogICAgICAgICAgICAgICAgPHNwYW4gY2xhc3NOYW1lPSJtZXRyaWMtbGFiZWwiPuyLnOqzteq4sOqwhDwvc3Bhbj4KICAgICAgICAgICAgICAgIDxzcGFuIGNsYXNzTmFtZT0ibWV0cmljLXZhbHVlIj57cmVzdWx0cy5jb25zdFBlcmlvZH3qsJzsm5Q8L3NwYW4+CiAgICAgICAgICAgICAgPC9kaXY+CiAgICAgICAgICAgIDwvZGl2PgogICAgICAgICAgPC9kaXY+CiAgICAgICAgKX0KICAgICAgICAKICAgICAgICB7ZmFjJiYoCiAgICAgICAgICA8ZGl2IGNsYXNzTmFtZT0ic2VjdGlvbiI+CiAgICAgICAgICAgIDxkaXYgY2xhc3NOYW1lPSJzZWN0aW9uLXRpdGxlIj7wn4+iIOyLnOyEpOuzhCDqsJzsmpQ8L2Rpdj4KICAgICAgICAgICAgPGRpdiBzdHlsZT17e292ZXJmbG93WDonYXV0byd9fT4KICAgICAgICAgICAgICA8dGFibGU+CiAgICAgICAgICAgICAgICA8dGhlYWQ+CiAgICAgICAgICAgICAgICAgIDx0cj4KICAgICAgICAgICAgICAgICAgICA8dGg+6rWs67aEPC90aD4KICAgICAgICAgICAgICAgICAgICA8dGg+7J6E64yA7ZiV6riw7IiZ7IKsPC90aD4KICAgICAgICAgICAgICAgICAgICA8dGg+7Jik7ZS87Iqk7YWUPC90aD4KICAgICAgICAgICAgICAgICAgICA8dGg+6rSA6rSR7Zi47YWUPC90aD4KICAgICAgICAgICAgICAgICAgICA8dGg+6re866aw7IOd7ZmcPC90aD4KICAgICAgICAgICAgICAgICAgICA8dGg+7ZWp6rOEPC90aD4KICAgICAgICAgICAgICAgICAgPC90cj4KICAgICAgICAgICAgICAgIDwvdGhlYWQ+CiAgICAgICAgICAgICAgICA8dGJvZHk+CiAgICAgICAgICAgICAgICAgIDx0cj4KICAgICAgICAgICAgICAgICAgICA8dGQ+7Jqp7KCB66WgIOu5hOycqDwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnJhdGlvcy5kb3JtKjEwMCwxKX0lPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMucmF0aW9zLm9mZmljZXRlbCoxMDAsMSl9JTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnJhdGlvcy5ob3RlbCoxMDAsMSl9JTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnJhdGlvcy5yZXRhaWwqMTAwLDEpfSU8L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD4xMDAuMCU8L3RkPgogICAgICAgICAgICAgICAgICA8L3RyPgogICAgICAgICAgICAgICAgICA8dHIgY2xhc3NOYW1lPSJoaWdobGlnaHQtcm93Ij4KICAgICAgICAgICAgICAgICAgICA8dGQ+7KeA7IOBIOyXsOuptOyggSjjjqEpPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuZG9ybS5ncm91bmQsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMub2ZmaWNldGVsLmdyb3VuZCwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5ob3RlbC5ncm91bmQsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMucmV0YWlsLmdyb3VuZCwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy50b3RhbHMuZ3JvdW5kLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0ciBjbGFzc05hbWU9InN1Yi1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7ilJQg7Iuc7ISk66m07KCBPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuZG9ybS5mYWNpbGl0eUFyZWEsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMub2ZmaWNldGVsLmZhY2lsaXR5QXJlYSwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5ob3RlbC5mYWNpbGl0eUFyZWEsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMucmV0YWlsLmZhY2lsaXR5QXJlYSwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy50b3RhbHMuZmFjaWxpdHlBcmVhLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0ciBjbGFzc05hbWU9InN1Yi1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7ilJQg7KO87LCo7YOA7JuMPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuZG9ybS5wYXJraW5nVG93ZXIsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMub2ZmaWNldGVsLnBhcmtpbmdUb3dlciwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5ob3RlbC5wYXJraW5nVG93ZXIsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMucmV0YWlsLnBhcmtpbmdUb3dlciwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy50b3RhbHMucGFya2luZ1Rvd2VyLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0ciBjbGFzc05hbWU9ImhpZ2hsaWdodC1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7sp4DtlZgg7Jew66m07KCBKOOOoSk8L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5kb3JtLnVuZGVyLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLm9mZmljZXRlbC51bmRlciwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5ob3RlbC51bmRlciwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5yZXRhaWwudW5kZXIsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMudG90YWxzLnVuZGVyLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0ciBjbGFzc05hbWU9InN1Yi1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7ilJQg7KeA7ZWY6rO17JqpPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuZG9ybS51bmRlclNoYXJlZCwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5vZmZpY2V0ZWwudW5kZXJTaGFyZWQsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuaG90ZWwudW5kZXJTaGFyZWQsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMucmV0YWlsLnVuZGVyU2hhcmVkLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnRvdGFscy51bmRlclNoYXJlZCwyKX08L3RkPgogICAgICAgICAgICAgICAgICA8L3RyPgogICAgICAgICAgICAgICAgICA8dHIgY2xhc3NOYW1lPSJzdWItcm93Ij4KICAgICAgICAgICAgICAgICAgICA8dGQ+4pSUIOyjvOywqOyepTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLmRvcm0ucGFya2luZ0xvdCwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5vZmZpY2V0ZWwucGFya2luZ0xvdCwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5ob3RlbC5wYXJraW5nTG90LDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnJldGFpbC5wYXJraW5nTG90LDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnRvdGFscy5wYXJraW5nTG90LDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0ciBjbGFzc05hbWU9InN1Yi1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7ilJQg6rO17Jyg6rO16rCEKOyngO2VmCk8L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5kb3JtLnNoYXJlZFVuZGVyLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLm9mZmljZXRlbC5zaGFyZWRVbmRlciwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5ob3RlbC5zaGFyZWRVbmRlciwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5yZXRhaWwuc2hhcmVkVW5kZXIsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMudG90YWxzLnNoYXJlZFVuZGVyLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0ciBjbGFzc05hbWU9InN1Yi1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7ilJQg6riw7KCE7IukPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuZG9ybS5tZWNoRWxlYywyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5vZmZpY2V0ZWwubWVjaEVsZWMsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuaG90ZWwubWVjaEVsZWMsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMucmV0YWlsLm1lY2hFbGVjLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnRvdGFscy5tZWNoRWxlYywyKX08L3RkPgogICAgICAgICAgICAgICAgICA8L3RyPgogICAgICAgICAgICAgICAgICA8dHIgY2xhc3NOYW1lPSJ0b3RhbC1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7si5zshKTrs4Qg7Jew66m07KCBKOOOoSk8L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5kb3JtLnRvdGFsLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLm9mZmljZXRlbC50b3RhbCwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5ob3RlbC50b3RhbCwyKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5yZXRhaWwudG90YWwsMil9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMudG90YWxzLnRvdGFsLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0cj4KICAgICAgICAgICAgICAgICAgICA8dGQ+7Jew66m07KCBIOu5hOycqDwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoKGZhYy5kb3JtLnRvdGFsL2ZhYy50b3RhbHMudG90YWwpKjEwMCwxKX0lPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdCgoZmFjLm9mZmljZXRlbC50b3RhbC9mYWMudG90YWxzLnRvdGFsKSoxMDAsMSl9JTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoKGZhYy5ob3RlbC50b3RhbC9mYWMudG90YWxzLnRvdGFsKSoxMDAsMSl9JTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoKGZhYy5yZXRhaWwudG90YWwvZmFjLnRvdGFscy50b3RhbCkqMTAwLDEpfSU8L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD4xMDAuMCU8L3RkPgogICAgICAgICAgICAgICAgICA8L3RyPgogICAgICAgICAgICAgICAgICA8dHIgY2xhc3NOYW1lPSJoaWdobGlnaHQtcm93Ij4KICAgICAgICAgICAgICAgICAgICA8dGQ+6rO17Jyg6rO16rCEKOOOoSk8L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD4tPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+LTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPi08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD4tPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMudG90YWxzLnNoYXJlZFNwYWNlLDIpfTwvdGQ+CiAgICAgICAgICAgICAgICAgIDwvdHI+CiAgICAgICAgICAgICAgICAgIDx0ciBjbGFzc05hbWU9InN1Yi1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7ilJQg7KeA7IOBPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+LTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPi08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD4tPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+LTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLnRvdGFscy5zaGFyZWRTcGFjZUdyb3VuZCwyKX08L3RkPgogICAgICAgICAgICAgICAgICA8L3RyPgogICAgICAgICAgICAgICAgICA8dHIgY2xhc3NOYW1lPSJzdWItcm93Ij4KICAgICAgICAgICAgICAgICAgICA8dGQ+4pSUIOyngO2VmDwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPi08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD4tPC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+LTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPi08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy50b3RhbHMuc2hhcmVkU3BhY2VVbmRlciwyKX08L3RkPgogICAgICAgICAgICAgICAgICA8L3RyPgogICAgICAgICAgICAgICAgICA8dHIgY2xhc3NOYW1lPSJ0b3RhbC1yb3ciPgogICAgICAgICAgICAgICAgICAgIDx0ZD7tmLjsi6TsiJgo7IS464yAKTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLmRvcm0udW5pdHMsMCl9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMub2ZmaWNldGVsLnVuaXRzLDApfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPntmbXQoZmFjLmhvdGVsLnVuaXRzLDApfTwvdGQ+CiAgICAgICAgICAgICAgICAgICAgPHRkPi08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy50b3RhbHMudW5pdHMsMCl9PC90ZD4KICAgICAgICAgICAgICAgICAgPC90cj4KICAgICAgICAgICAgICAgICAgPHRyPgogICAgICAgICAgICAgICAgICAgIDx0ZD7so7zssKjrjIDsiJg8L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5kb3JtLnBhcmtpbmcsMCl9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMub2ZmaWNldGVsLnBhcmtpbmcsMCl9PC90ZD4KICAgICAgICAgICAgICAgICAgICA8dGQ+e2ZtdChmYWMuaG90ZWwucGFya2luZywwKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy5yZXRhaWwucGFya2luZywwKX08L3RkPgogICAgICAgICAgICAgICAgICAgIDx0ZD57Zm10KGZhYy50b3RhbHMucGFya2luZywwKX08L3RkPgogICAgICAgICAgICAgICAgICA8L3RyPgogICAgICAgICAgICAgICAgPC90Ym9keT4KICAgICAgICAgICAgICA8L3RhYmxlPgogICAgICAgICAgICA8L2Rpdj4KICAgICAgICAgIDwvZGl2PgogICAgICAgICl9CiAgICAgICAgCiAgICAgIDwvZGl2PgogICAgPC9kaXY+CiAgKTsKfQpSZWFjdERPTS5yZW5kZXIoPEFwcC8+LGRvY3VtZW50LmdldEVsZW1lbnRCeUlkKCdyb290JykpOwo8L3NjcmlwdD4KPC9ib2R5Pgo8L2h0bWw+"""
CALC_HTML = base64.b64decode(_HTML_B64).decode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/") or "/"
        if p in ("/", "/calculator", "/index.html", "/calculator.html"):
            self._html(CALC_HTML)
        elif p == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif p == "/debug":
            self._handle_debug()
        else:
            self._html("<meta charset=UTF-8><h2>404</h2><p><a href='/'>계산기</a></p>", 404)

    def _handle_debug(self):
        """VWorld API 디버그 — /debug?address=서울시+강남구+역삼동+812-13"""
        from urllib.parse import urlparse, parse_qs as qparse
        qs = qparse(urlparse(self.path).query)
        address = qs.get("address", ["서울특별시 강남구 역삼동 812-13"])[0]
        out = {"address": address, "steps": []}
        try:
            out["steps"].append("1. geocode_address 호출")
            geo = geocode_address(address)
            out["geocode"] = str(geo)[:500] if geo else "None"
            if geo:
                point = geo.get("result", {}).get("point", {})
                x, y = point.get("x"), point.get("y")
                out["coord"] = {"x": x, "y": y}
                out["steps"].append("2. get_pnu_from_coord 호출")
                pnu = get_pnu_from_coord(float(x), float(y)) if x and y else None
                out["pnu"] = pnu
                if pnu:
                    out["steps"].append("3. method2_vworld_api 호출")
                    zone = method2_vworld_api(address)
                    out["method2_result"] = zone
                else:
                    out["steps"].append("PNU 생성 실패")
            else:
                out["steps"].append("Geocoding 실패")
        except Exception as e:
            import traceback
            out["error"] = str(e)
            out["traceback"] = traceback.format_exc()
        self._json(200, out)

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in [
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Allow-Methods", "POST, GET, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type"),
            ("Content-Length", "0"),
        ]:
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        if self.path == "/search":
            self._handle_search()
        else:
            self.send_error(404)

    def _html(self, html: str, status: int = 200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, data: Dict[str, Any]):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _handle_search(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n).decode("utf-8")

        address = ""
        ct = self.headers.get("Content-Type", "")
        if "application/json" in ct:
            try:
                address = json.loads(body).get("address", "").strip()
            except json.JSONDecodeError:
                pass
        else:
            address = parse_qs(body).get("address", [""])[0].strip()

        if not address:
            self._json(400, {"error": "주소를 입력해주세요."})
            return

        result: Dict[str, Any] = {"address": address, "method1": None, "method2": None, "final": None}

        try:
            _pnu_cache.clear()
            # 방법 2: VWorld API (우선 — 클라우드 환경에서 안정적)
            try:
                result["method2"] = method2_vworld_api(address)
            except Exception as e2:
                log_debug(f"⚠️ VWorld API 실패: {e2}")
                result["method2_error"] = str(e2)
            # 방법 1: 토지이음 스크래핑 (보조)
            try:
                result["method1"] = method1_eum_scraping(address)
            except Exception as e1:
                log_debug(f"⚠️ 토지이음 스크래핑 실패: {e1}")
                result["method1_error"] = str(e1)
            # VWorld API 결과 우선, 없으면 토지이음 결과 사용
            result["final"] = result["method2"] or result["method1"]
        except Exception as e:
            import traceback
            log_debug(f"❌ 전체 오류: {traceback.format_exc()}")
            result["error"] = str(e)

        self._json(200, result)

    def log_message(self, fmt, *args):
        if DEBUG_MODE:
            sys.stderr.write(f"[HTTP] {fmt % args}\n")


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "알 수 없음"


def parse_args() -> Dict[str, Any]:
    global DEBUG_MODE
    args: Dict[str, Any] = {"host": DEFAULT_HOST, "port": DEFAULT_PORT}
    
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--port" and i + 1 < len(sys.argv):
            args["port"] = int(sys.argv[i + 1])
            i += 2
        elif arg == "--host" and i + 1 < len(sys.argv):
            args["host"] = sys.argv[i + 1]
            i += 2
        elif arg == "--local":
            args["host"] = "127.0.0.1"
            i += 1
        elif arg == "--debug":
            DEBUG_MODE = True
            i += 1
        elif arg in ("--help", "-h"):
            print(__doc__)
            sys.exit(0)
        else:
            i += 1
    
    return args


def main():
    args = parse_args()
    host = args["host"]
    port = args["port"]
    
    srv = Server((host, port), Handler)
    local_ip = get_local_ip()
    
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  🏗️  약식 규모검토 계산기 v2.0")
    print(f"  ✨ 여러 용도지역 처리 개선")
    if DEBUG_MODE:
        print(f"  🔍 서버 디버그 모드: ON")
    print(f"{sep}")
    print(f"  🚀 서버: http://localhost:{port}")
    if host == "0.0.0.0":
        print(f"  🌐 내부망: http://{local_ip}:{port}")
    print(f"{sep}\n")
    
    if DEBUG_MODE:
        print("✅ 서버 디버그 로그가 아래에 표시됩니다.\n", file=sys.stderr)
    
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n서버 종료")
        srv.server_close()


if __name__ == "__main__":
    main()
