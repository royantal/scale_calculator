# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 언어 지침

- 모든 결과값과 설명은 반드시 한글로 작성한다.

## Project Overview

Korean land use zone (용도지역) lookup tool. Takes a Korean address, converts it to a PNU (Parcel Number), then queries the zone classification using two methods:

1. **Method 1**: Web scraping from 토지이음 (eum.go.kr) via Selenium headless Chrome
2. **Method 2**: Direct API calls to VWorld (api.vworld.kr)

Both methods are run and their results compared.

## Running

```bash
python3 land_use_zone.py "서울특별시 강남구 역삼동 812-13"
```

## Dependencies

```bash
pip3 install selenium
```

No requirements.txt — `selenium` is the only external dependency. The rest uses stdlib (`urllib`, `json`, `re`, `time`, `sys`).

## Architecture (land_use_zone.py)

Single-file script (~655 lines) with these logical sections:

1. **Address → PNU conversion** (top): `geocode_address()` → `address_to_pnu()` with caching (`_pnu_cache`). Multiple fallback paths: VWorld geocoding → coordinate-based reverse geocoding → manual PNU assembly from parsed address components.

2. **Method 1 — eum.go.kr scraping** (middle): `method1_eum_scraping()` uses Selenium to load the 토지이음 page with a PNU parameter, then extracts zone info from embedded JavaScript variables (`sehUcodeListExt`).

3. **Method 2 — VWorld API** (lower): `method2_vworld_api()` calls `getLandUseAttr` endpoint with PNU. Falls back to WFS data service (`vworld_data_api_fallback()`) if the primary endpoint fails.

4. **Main** (bottom): Parses CLI argument, runs both methods, compares and prints results.

## Key Details

- VWorld API key is hardcoded as `VWORLD_API_KEY` at line 26
- PNU is a 19-digit Korean parcel identifier built from: 시도(2) + 시군구(3) + 읍면동(3) + 리(2) + 대지구분(1) + 본번(4) + 부번(4)
- Zone results are filtered to exclude broad categories (용도지역, 용도지구, 용도구역) and return only specific zones (e.g., 제2종일반주거지역)
- `sido_code` dictionary maps Korean province names to 2-digit codes
