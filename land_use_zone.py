"""
용도지역 자동 조회 스크립트
- 방법 1: 토지이음(eum.go.kr) 웹 스크래핑 (Selenium)
- 방법 2: VWorld API 직접 호출

사용법:
    python3 land_use_zone.py "서울특별시 강남구 역삼동 812-13"
    python3 land_use_zone.py "경기도 성남시 분당구 정자동 178-1"
"""

from __future__ import annotations

import sys
import re
import json
import time
import urllib.parse
import urllib.request
from typing import Optional, Tuple


# ──────────────────────────────────────────────
# 공통: 주소 → PNU 변환 (VWorld Geocoding + 법정동코드)
# ──────────────────────────────────────────────

VWORLD_API_KEY = "DB07E3CD-6F12-388C-99D4-6779EA88652F"

# PNU 캐시 (같은 주소에 대해 중복 API 호출 방지)
_pnu_cache: dict[str, Optional[str]] = {}


def geocode_address(address: str) -> dict | None:
    """VWorld Geocoding API로 주소를 좌표 및 구조화된 정보로 변환"""
    params = urllib.parse.urlencode({
        "service": "address",
        "request": "getcoord",
        "version": "2.0",
        "crs": "epsg:4326",
        "address": address,
        "refine": "true",
        "simple": "false",
        "format": "json",
        "type": "PARCEL",
        "key": VWORLD_API_KEY,
    })
    url = f"https://api.vworld.kr/req/address?{params}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if data.get("response", {}).get("status") == "OK":
            return data["response"]
        else:
            print(f"  [Geocoding 실패] {data}")
            return None
    except Exception as e:
        print(f"  [Geocoding 오류] {e}")
        return None


def address_to_pnu(address: str) -> str | None:
    """
    주소 문자열에서 PNU(19자리)를 생성한다.
    VWorld Geocoding으로 법정동코드를 얻고, 지번 파싱으로 본번/부번을 추출.
    """
    if address in _pnu_cache:
        cached = _pnu_cache[address]
        if cached:
            print(f"  [PNU 캐시] {cached}")
        return cached

    geo = geocode_address(address)
    if not geo:
        return None

    # refined 주소에서 법정동코드 추출 시도
    result = geo.get("result", {})
    point = result.get("point", {})
    refined = result.get("refined", {})

    # 구조화된 주소에서 정보 추출
    structure = refined.get("structure", {})

    # 법정동코드를 가져오기 위해 VWorld 검색 API 사용
    x = point.get("x")
    y = point.get("y")

    if not x or not y:
        print("  [PNU 변환 실패] 좌표를 얻을 수 없습니다.")
        return None

    # 좌표로 PNU 조회 (VWorld Data API 이용)
    pnu = get_pnu_from_coord(float(x), float(y))
    if pnu:
        _pnu_cache[address] = pnu
        return pnu

    # fallback: 주소 파싱으로 PNU 생성 시도
    result = parse_address_to_pnu(address, structure)
    _pnu_cache[address] = result
    return result


def get_pnu_from_coord(x: float, y: float) -> str | None:
    """좌표로부터 PNU를 조회 (VWorld 역지오코딩)"""
    params = urllib.parse.urlencode({
        "service": "address",
        "request": "getAddress",
        "version": "2.0",
        "crs": "epsg:4326",
        "point": f"{x},{y}",
        "format": "json",
        "type": "PARCEL",
        "key": VWORLD_API_KEY,
    })
    url = f"https://api.vworld.kr/req/address?{params}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        status = data.get("response", {}).get("status")
        if status == "OK":
            results = data["response"]["result"]
            if isinstance(results, list) and len(results) > 0:
                item = results[0]
            else:
                item = results

            structure = item.get("structure", {})
            level5 = structure.get("level5", "")   # 지번
            # level4LC에 법정동코드 10자리가 직접 포함되어 있음
            level4LC = structure.get("level4LC", "")

            full_text = item.get("text", "")
            print(f"  [역지오코딩] {full_text}")

            # 지번 파싱 (본번-부번)
            main_num, sub_num = parse_jibun(level5)

            # 산/대지 구분
            land_type = "2" if "산" in level5 else "1"

            if level4LC and len(level4LC) == 10:
                pnu = f"{level4LC}{land_type}{main_num:04d}{sub_num:04d}"
                print(f"  [PNU 생성] {pnu} (법정동코드: {level4LC})")
                return pnu

            # fallback: 검색 API로 법정동코드 조회
            level1 = structure.get("level1", "")
            level2 = structure.get("level2", "")
            level4L = structure.get("level4L", "")
            bjdong_code = get_bjdong_code(level1, level2, level4L)
            if bjdong_code:
                pnu = f"{bjdong_code}{land_type}{main_num:04d}{sub_num:04d}"
                return pnu

    except Exception as e:
        print(f"  [역지오코딩 오류] {e}")

    return None


def parse_jibun(jibun_str: str) -> tuple[int, int]:
    """지번 문자열에서 본번과 부번을 추출"""
    jibun_str = jibun_str.replace("산", "").strip()
    match = re.search(r"(\d+)(?:-(\d+))?", jibun_str)
    if match:
        main_num = int(match.group(1))
        sub_num = int(match.group(2)) if match.group(2) else 0
        return main_num, sub_num
    return 0, 0


# 주요 시/도 법정동코드 매핑
SIDO_CODE = {
    "서울특별시": "11", "서울": "11",
    "부산광역시": "26", "부산": "26",
    "대구광역시": "27", "대구": "27",
    "인천광역시": "28", "인천": "28",
    "광주광역시": "29", "광주": "29",
    "대전광역시": "30", "대전": "30",
    "울산광역시": "31", "울산": "31",
    "세종특별자치시": "36", "세종": "36",
    "경기도": "41", "경기": "41",
    "강원특별자치도": "42", "강원도": "42", "강원": "42",
    "충청북도": "43", "충북": "43",
    "충청남도": "44", "충남": "44",
    "전라북도": "45", "전북특별자치도": "45", "전북": "45",
    "전라남도": "46", "전남": "46",
    "경상북도": "47", "경북": "47",
    "경상남도": "48", "경남": "48",
    "제주특별자치도": "50", "제주": "50",
}


def get_bjdong_code(sido: str, sigungu: str, dong: str) -> str | None:
    """VWorld 검색 API로 법정동코드(10자리)를 조회"""
    search_term = f"{sido} {sigungu} {dong}"
    params = urllib.parse.urlencode({
        "service": "search",
        "request": "search",
        "version": "2.0",
        "crs": "epsg:4326",
        "size": "1",
        "page": "1",
        "query": search_term,
        "type": "district",
        "category": "L4",
        "format": "json",
        "errorformat": "json",
        "key": VWORLD_API_KEY,
    })
    url = f"https://api.vworld.kr/req/search?{params}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        status = data.get("response", {}).get("status")
        if status == "OK":
            items = data["response"]["result"]["items"]
            if items:
                item = items[0]
                # id 필드에 법정동코드가 들어있음
                bjdong_code = item.get("id", "")
                if len(bjdong_code) >= 10:
                    return bjdong_code[:10]
    except Exception as e:
        print(f"  [법정동코드 조회 오류] {e}")

    # fallback: 간단한 시도코드만이라도
    return None


def parse_address_to_pnu(address: str, structure: dict) -> str | None:
    """주소 문자열을 직접 파싱하여 PNU를 생성 (fallback)"""
    # 지번 추출
    match = re.search(r"(\d+)(?:-(\d+))?(?:\s*$)", address.strip())
    if not match:
        return None

    main_num = int(match.group(1))
    sub_num = int(match.group(2)) if match.group(2) else 0
    land_type = "1"
    if "산" in address:
        land_type = "2"

    # 시/도 코드
    sido = structure.get("level1", "")
    sigungu = structure.get("level2", "")
    dong = structure.get("level4L", "") or structure.get("level4A", "")

    bjdong_code = get_bjdong_code(sido, sigungu, dong)
    if bjdong_code:
        pnu = f"{bjdong_code}{land_type}{main_num:04d}{sub_num:04d}"
        return pnu

    return None


# ──────────────────────────────────────────────
# 방법 1: 토지이음(eum.go.kr) 웹 스크래핑
# ──────────────────────────────────────────────

def method1_eum_scraping(address: str) -> str | None:
    """
    토지이음 사이트에서 PNU를 사용해 용도지역을 스크래핑.
    Selenium을 사용하여 동적 페이지를 처리.
    """
    print("\n[방법 1] 토지이음(eum.go.kr) 웹 스크래핑")
    print("=" * 50)

    # 1) 주소 → PNU 변환
    print(f"  주소: {address}")
    print("  PNU 변환 중...")
    pnu = address_to_pnu(address)
    if not pnu:
        print("  [실패] PNU를 생성할 수 없습니다.")
        return None

    print(f"  PNU: {pnu}")

    # 2) Selenium으로 토지이음 페이지 접속
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
    except ImportError:
        print("  [오류] selenium 패키지가 필요합니다: pip install selenium")
        return None

    url = (
        f"https://www.eum.go.kr/web/ar/lu/luLandDet.jsp"
        f"?pnu={pnu}&mode=search&isNoScr=script&selGbn=umd"
    )
    print(f"  토지이음 URL: {url}")

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.get(url)
        print("  페이지 로딩 중...")

        # 페이지 로딩 대기 (동적 콘텐츠)
        time.sleep(5)

        # JavaScript 변수에서 용도지역 데이터 추출
        # sehUcodeListExt 변수에 용도지역 정보가 있음
        try:
            seh_data = driver.execute_script(
                "return typeof sehUcodeListExt !== 'undefined' ? sehUcodeListExt : null;"
            )
            if seh_data:
                print(f"  sehUcodeListExt: {seh_data}")
                zones = extract_zones_from_seh(seh_data)
                if zones:
                    return zones
        except Exception:
            pass

        # 페이지 소스에서 직접 추출 시도
        page_source = driver.page_source

        # sehUcodeListExt 변수 값 추출
        match = re.search(
            r'var\s+sehUcodeListExt\s*=\s*["\'](.+?)["\'];',
            page_source
        )
        if match:
            seh_raw = match.group(1)
            print(f"  sehUcodeListExt (소스): {seh_raw}")
            zones = extract_zones_from_seh(seh_raw)
            if zones:
                return zones

        # 「국토의 계획 및 이용에 관한 법률」 관련 텍스트 검색
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
                # 중복 제거
                seen = set()
                unique = []
                for z in zone_names:
                    if z not in seen:
                        seen.add(z)
                        unique.append(z)
                return ", ".join(unique)
        except Exception:
            pass

        print("  [실패] 용도지역 정보를 찾을 수 없습니다.")
        return None

    except Exception as e:
        print(f"  [오류] {e}")
        return None
    finally:
        if driver:
            driver.quit()


def extract_zones_from_seh(seh_data: str) -> str | None:
    """
    sehUcodeListExt 데이터에서 용도지역명을 추출.

    토지이음의 「국토의 계획 및 이용에 관한 법률」 셀에서
    첫번째 ,와 두번째 , 사이의 단어가 실제 용도지역.
    예: "도시지역, 제2종일반주거지역" → "제2종일반주거지역"

    sehUcodeListExt 형식:
    [{ucode=UQA01X, uname=도시지역}, {ucode=UQA122, uname=제2종일반주거지역}]
    → 첫 번째는 대분류(도시지역 등), 두 번째가 구체적 용도지역
    """
    # uname= 패턴으로 추출
    names = re.findall(r'uname=([^,}\]]+)', seh_data)
    if not names:
        # JSON 형식 시도
        try:
            items = json.loads(seh_data.replace("'", '"'))
            names = [item.get("uname", "") for item in items if item.get("uname")]
        except Exception:
            pass

    if not names:
        return None

    names = [n.strip() for n in names]

    # 사용자 기준: 첫번째 , 와 두번째 , 사이 = 두 번째 항목이 용도지역
    if len(names) >= 2:
        return names[1]  # 구체적 용도지역 (예: 제2종일반주거지역)

    return names[0]


# ──────────────────────────────────────────────
# 방법 2: VWorld API로 용도지역 조회
# ──────────────────────────────────────────────

def method2_vworld_api(address: str) -> str | None:
    """
    VWorld API를 사용하여 용도지역을 조회.
    주소 → PNU → 토지이용계획 정보 API 호출
    """
    print("\n[방법 2] VWorld API")
    print("=" * 50)

    print(f"  주소: {address}")
    print("  PNU 변환 중...")
    pnu = address_to_pnu(address)
    if not pnu:
        print("  [실패] PNU를 생성할 수 없습니다.")
        return None

    print(f"  PNU: {pnu}")

    # getLandUseAttr API 호출
    print("  토지이용계획 정보 조회 중...")
    params = urllib.parse.urlencode({
        "key": VWORLD_API_KEY,
        "pnu": pnu,
        "numOfRows": "100",
        "format": "json",
    })
    url = f"https://api.vworld.kr/ned/data/getLandUseAttr?{params}"

    # 용도지역에 해당하는 코드 (UQA로 시작하는 것이 용도지역)
    # UQA01X=도시지역, UQA111=제1종전용주거, UQA112=제1종일반주거,
    # UQA121=제2종전용주거, UQA122=제2종일반주거, UQA123=제2종일반주거(7층이하),
    # UQA130=제3종일반주거, UQA210=중심상업, UQA220=일반상업,
    # UQA230=근린상업, UQA240=유통상업, UQA310=전용공업,
    # UQA320=일반공업, UQA330=준공업, UQA410=보전녹지,
    # UQA420=생산녹지, UQA430=자연녹지,
    # UQA112=관리지역, UQA113=농림지역, UQA114=자연환경보전지역
    ZONE_CODE_PREFIX = "UQA"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        land_uses = data.get("landUses", {})
        result_code = land_uses.get("resultCode", "")

        if result_code == "INCORRECT_KEY":
            print("  [실패] API 키 인증 실패")
            print("         getLandUseAttr API는 별도의 데이터 API 키 인증이 필요할 수 있습니다.")
            print("         VWorld(vworld.kr)에서 데이터 API 권한을 확인하세요.")
            print("\n  [대안] VWorld Data API (WFS) 시도 중...")
            return vworld_data_api_fallback(pnu, address)

        # resultCode가 OK이거나 빈 문자열이어도 field 데이터가 있으면 성공
        fields = land_uses.get("field", [])
        if not isinstance(fields, list):
            fields = [fields]

        if not fields:
            print("  [실패] 용도지역 데이터가 비어있습니다.")
            return None

        # 전체 규제 목록 표시
        all_zones = []
        yongdo_zones = []
        for field in fields:
            code = field.get("prposAreaDstrcCode", "")
            name = field.get("prposAreaDstrcCodeNm", "")
            if name:
                all_zones.append(f"    - {name} ({code})")
                # 용도지역만 필터 (UQA 코드)
                if code.startswith(ZONE_CODE_PREFIX):
                    yongdo_zones.append(name)

        print("  전체 토지이용규제 목록:")
        for z in all_zones:
            print(z)

        if yongdo_zones:
            # 대분류(도시지역/관리지역/농림지역/자연환경보전지역)를 제거하고
            # 구체적 용도지역만 반환 (예: 제2종일반주거지역)
            broad_categories = {
                "도시지역", "관리지역", "농림지역", "자연환경보전지역",
                "주거지역", "상업지역", "공업지역", "녹지지역",
                "용도미지정"
            }
            specific = [n for n in yongdo_zones if n not in broad_categories]
            if specific:
                # 중복 제거
                seen = set()
                unique = []
                for s in specific:
                    if s not in seen:
                        seen.add(s)
                        unique.append(s)
                return ", ".join(unique)
            # 구체적인 것이 없으면 전체 반환
            return ", ".join(yongdo_zones)

        # UQA 코드가 없으면 전체 반환
        all_names = [f.get("prposAreaDstrcCodeNm", "") for f in fields if f.get("prposAreaDstrcCodeNm")]
        return ", ".join(all_names) if all_names else None

    except Exception as e:
        print(f"  [오류] {e}")
        return None


def _pnu_to_address_parts(pnu: str, address: str) -> tuple[str, str, str] | None:
    """PNU와 주소로부터 시도명, 시군구명, 지번을 추출"""
    # 1) geocode 캐시에서 구조화된 주소 가져오기
    geo = geocode_address(address)
    if geo:
        structure = (
            geo.get("response", {})
            .get("refined", {})
            .get("structure", {})
        )
        sido = structure.get("level1", "")
        sigungu = structure.get("level2", "")
        jibun = structure.get("level5", "")
        if sido and sigungu:
            print(f"    주소 분해: 시도={sido}, 시군구={sigungu}, 지번={jibun}")
            return sido, sigungu, jibun

    # 2) PNU에서 직접 파싱 (시도코드 2자리 → 시도명 역매핑)
    if len(pnu) >= 5:
        sido_cd = pnu[:2]
        # 역매핑: 코드 → 대표 시도명
        code_to_sido = {}
        for name, code in SIDO_CODE.items():
            if code == sido_cd and name not in code_to_sido.values():
                if len(name) > len(code_to_sido.get(code, "")):
                    code_to_sido[code] = name
        sido = code_to_sido.get(sido_cd, "")
        if sido:
            print(f"    PNU 분해: 시도코드={sido_cd} → {sido}")
            # 지번: 대지구분(1) + 본번(4) + 부번(4)
            if len(pnu) == 19:
                main_num = int(pnu[11:15])
                sub_num = int(pnu[15:19])
                jibun = f"{main_num}-{sub_num}" if sub_num else str(main_num)
                return sido, "", jibun
            return sido, "", ""

    return None


def _wfs_query(layer_id: str, layer_name: str, attr_filter: str) -> list[str]:
    """WFS Data API 단일 레이어 조회"""
    params = urllib.parse.urlencode({
        "service": "data",
        "request": "GetFeature",
        "data": layer_id,
        "key": VWORLD_API_KEY,
        "domain": "localhost",
        "attrFilter": attr_filter,
        "format": "json",
        "size": "100",
    })
    url = f"https://api.vworld.kr/req/data?{params}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        status = data.get("response", {}).get("status")
        if status == "OK":
            features = (
                data["response"]
                .get("result", {})
                .get("featureCollection", {})
                .get("features", [])
            )
            zones = []
            for feat in features:
                props = feat.get("properties", {})
                zone = props.get("gj_nm", "") or props.get("name", "")
                if zone:
                    zones.append(zone)
            return zones
        elif status == "ERROR":
            err = data.get("response", {}).get("error", {})
            code = err.get("code", "")
            if code == "INCORRECT_KEY":
                print(f"    {layer_name}: API 키 인증 실패")
            elif code == "INVALID_RANGE":
                return []  # 필터 속성 미지원 → 빈 결과 반환
    except Exception:
        pass

    return []


def vworld_data_api_fallback(pnu: str, address: str) -> str | None:
    """VWorld Data API (WFS)를 사용한 대안 조회"""
    # 용도지역 관련 레이어들
    layers = [
        ("LT_C_UQ111", "도시지역"),
        ("LT_C_UQ112", "관리지역"),
        ("LT_C_UQ113", "농림지역"),
        ("LT_C_UQ114", "자연환경보전지역"),
    ]

    # ── 1차 시도: PNU 직접 필터 ──
    print("    [1차] PNU 필터 시도...")
    found_zones = []
    pnu_filter_failed = False

    for layer_id, layer_name in layers:
        attr_filter = f"pnu:=:{pnu}"
        params = urllib.parse.urlencode({
            "service": "data",
            "request": "GetFeature",
            "data": layer_id,
            "key": VWORLD_API_KEY,
            "domain": "localhost",
            "attrFilter": attr_filter,
            "format": "json",
            "size": "10",
        })
        url = f"https://api.vworld.kr/req/data?{params}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            status = data.get("response", {}).get("status")
            if status == "OK":
                features = (
                    data["response"]
                    .get("result", {})
                    .get("featureCollection", {})
                    .get("features", [])
                )
                for feat in features:
                    props = feat.get("properties", {})
                    zone = props.get("gj_nm", "") or props.get("name", "")
                    if zone:
                        found_zones.append(zone)
            elif status == "ERROR":
                err = data.get("response", {}).get("error", {})
                code = err.get("code", "")
                if code == "INCORRECT_KEY":
                    print(f"    {layer_name}: API 키 인증 실패")
                    continue
                if code == "INVALID_RANGE":
                    pnu_filter_failed = True
                    break
        except Exception:
            continue

    if found_zones:
        return ", ".join(found_zones)

    # ── 2차 시도: PNU를 시도/시군구/지번으로 분해하여 필터 ──
    if pnu_filter_failed:
        print("    [2차] PNU 필터 미지원 → 시도/시군구 필터로 재시도...")
        parts = _pnu_to_address_parts(pnu, address)
        if not parts:
            print("  [실패] 주소 분해 실패")
            return None

        sido, sigungu, jibun = parts

        found_zones = []
        for layer_id, layer_name in layers:
            # 필터 조합: sido_name + sigg_name (있으면)
            if sigungu:
                attr_filter = f"sido_name:like:{sido}|sigg_name:like:{sigungu}"
            else:
                attr_filter = f"sido_name:like:{sido}"

            zones = _wfs_query(layer_id, layer_name, attr_filter)
            found_zones.extend(zones)

        if found_zones:
            # 중복 제거
            seen = set()
            unique = []
            for z in found_zones:
                if z not in seen:
                    seen.add(z)
                    unique.append(z)
            return ", ".join(unique)

    print("  [실패] WFS Data API에서도 조회 실패")
    return None


# ──────────────────────────────────────────────
# 메인 실행
# ──────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("사용법: python3 land_use_zone.py \"주소\"")
        print("예시:   python3 land_use_zone.py \"서울특별시 강남구 역삼동 812-13\"")
        print("        python3 land_use_zone.py \"경기도 성남시 분당구 정자동 178-1\"")
        sys.exit(1)

    address = sys.argv[1]
    print(f"\n{'='*60}")
    print(f"  용도지역 자동 조회")
    print(f"  입력 주소: {address}")
    print(f"{'='*60}")

    results = {}

    # 방법 1: 토지이음 스크래핑
    result1 = method1_eum_scraping(address)
    if result1:
        print(f"\n  ✓ [방법1 결과] 용도지역: {result1}")
        results["토지이음"] = result1
    else:
        print(f"\n  ✗ [방법1 결과] 조회 실패")

    # 방법 2: VWorld API
    result2 = method2_vworld_api(address)
    if result2:
        print(f"\n  ✓ [방법2 결과] 용도지역: {result2}")
        results["VWorld API"] = result2
    else:
        print(f"\n  ✗ [방법2 결과] 조회 실패")

    # 최종 결과 비교
    print(f"\n{'='*60}")
    print(f"  최종 결과 비교")
    print(f"{'='*60}")

    if not results:
        print("  두 방법 모두 실패했습니다.")
        print("  - VWorld API 키 권한을 확인하세요 (vworld.kr에서 데이터 API 신청)")
        print("  - 주소가 올바른지 확인하세요 (예: 서울특별시 강남구 역삼동 812-13)")
    else:
        for method_name, zone in results.items():
            print(f"  [{method_name}] {zone}")

        if len(results) == 2:
            if results.get("토지이음") == results.get("VWorld API"):
                print("\n  → 두 방법의 결과가 일치합니다.")
            else:
                print("\n  → 두 방법의 결과가 다릅니다.")
                print("    토지이음 결과가 더 정확할 가능성이 높습니다.")

    # 최종 용도지역 반환 (토지이음 우선)
    final = results.get("토지이음") or results.get("VWorld API")
    if final:
        print(f"\n  ★ 최종 용도지역: {final}")
    print()


if __name__ == "__main__":
    main()
