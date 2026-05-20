import http.server
import socketserver
import urllib.request
import re
import json

PORT = 8080

class Handler(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        if path.endswith('.php'):
            return 'text/html'
        return super().guess_type(path)

    def do_GET(self):
        if self.path == '/api_io_data.php' or self.path == '/api/io_data':
            try:
                url = "http://10.107.194.62/sbs/gtasrs_dashboard/gtasrs_dashboard_ctrl.php"
                req = urllib.request.Request(url)
                
                # Bypass system proxy for internal IP
                proxy_handler = urllib.request.ProxyHandler({})
                opener = urllib.request.build_opener(proxy_handler)
                with opener.open(req, timeout=5) as response:
                    html = response.read().decode('utf-8', errors='ignore')
                
                def extract(id_name):
                    match = re.search(rf"getElementById\('{id_name}'\)\.innerHTML\s*=\s*'([^']+)'", html)
                    return match.group(1) if match else "0"

                data = {
                    "entrada": extract("s1_inbound_total"),
                    "manual": extract("s1_outbound_cv31_actual"),
                    "auto": extract("s1_press_total"),
                    "rate_entrada": extract("s1_inbound_avg"),
                    "rate_manual": extract("s1_manual_rate"),
                    "rate_auto": extract("s1_press_rate")
                }
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))
            except Exception as e:
                print(f"Error in /api/io_data: {e}")
                self.send_response(500)
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
        else:
            super().do_GET()

with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"Serving at port {PORT}")
    httpd.serve_forever()
