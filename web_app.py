"""
용도지역 조회 웹 서버
Python 내장 http.server 기반, 외부 프레임워크 불필요.

실행:
    python3 web_app.py
    → http://localhost:8080 에서 접속
"""

import io
import json
import sys
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import parse_qs

# land_use_zone.py에서 기존 함수 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from land_use_zone import address_to_pnu, method1_eum_scraping, method2_vworld_api, _pnu_cache

PORT = 8080
HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        """CORS preflight 요청 처리"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if self.path == "/search":
            self._handle_search()
        else:
            self.send_error(404)

    def _serve_html(self):
        try:
            with open(HTML_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode("utf-8"))
        except FileNotFoundError:
            self.send_error(500, "index.html not found")

    def _handle_search(self):
        # POST body 읽기
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        # JSON 또는 form-urlencoded 파싱
        address = ""
        content_type = self.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                data = json.loads(body)
                address = data.get("address", "").strip()
            except json.JSONDecodeError:
                pass
        else:
            params = parse_qs(body)
            address = params.get("address", [""])[0].strip()

        if not address:
            self._send_json(400, {"error": "주소를 입력해주세요."})
            return

        result = {"address": address, "method1": None, "method2": None, "final": None, "log": ""}
        log_buffer = io.StringIO()
        log1 = io.StringIO()
        log2 = io.StringIO()

        try:
            # PNU 캐시 초기화 (매 요청마다 새로 조회)
            _pnu_cache.clear()

            # 먼저 PNU를 한번 변환해두어 캐시에 저장 (두 방법이 중복 호출 방지)
            # 메인 스레드의 stdout 캡처
            old_stdout = sys.stdout
            sys.stdout = log_buffer
            try:
                address_to_pnu(address)
            finally:
                sys.stdout = old_stdout

            # 방법 1, 방법 2를 병렬 실행 (각 스레드에서 자체 stdout 캡처)
            def run_method1():
                sys.stdout = log1
                try:
                    result["method1"] = method1_eum_scraping(address)
                except Exception as e:
                    result["method1_error"] = str(e)
                finally:
                    sys.stdout = sys.__stdout__

            def run_method2():
                sys.stdout = log2
                try:
                    result["method2"] = method2_vworld_api(address)
                except Exception as e:
                    result["method2_error"] = str(e)
                finally:
                    sys.stdout = sys.__stdout__

            t1 = threading.Thread(target=run_method1)
            t2 = threading.Thread(target=run_method2)
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # 최종 결과 (토지이음 우선)
            result["final"] = result["method1"] or result["method2"]

            # 일치 여부
            if result["method1"] and result["method2"]:
                result["match"] = result["method1"] == result["method2"]

        except Exception as e:
            result["error"] = str(e)

        result["log"] = log_buffer.getvalue() + log1.getvalue() + log2.getvalue()
        self._send_json(200, result)

    def _send_json(self, status_code, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # CORS 헤더 추가 (모든 origin 허용)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """서버 로그를 stderr로 출력"""
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), RequestHandler)
    print(f"서버 시작: http://localhost:{PORT}")
    print("종료하려면 Ctrl+C를 누르세요.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버 종료")
        server.server_close()


if __name__ == "__main__":
    main()
