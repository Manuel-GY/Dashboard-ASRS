import urllib.request
import traceback

try:
    url = 'http://10.107.194.70/cProduccion/horahora.php'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as response:
        html = response.read().decode('utf-8', errors='ignore')
        with open('horahora.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("Success! Saved to horahora.html")
except Exception as e:
    print(f"Error fetching URL: {e}")
    traceback.print_exc()
