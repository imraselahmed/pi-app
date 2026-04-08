from flask import Flask, request, jsonify
from flask_cors import CORS
from bs4 import BeautifulSoup
import requests, re
from urllib.parse import urljoin, urlparse

app = Flask(__name__)
CORS(app)

def classify_anchor(text, is_image):
    if is_image: return "image"
    if not text.strip(): return "empty"
    t = text.lower().strip()
    if t in ("click here", "read more", "learn more", "here", "this", "link", "more"):
        return "generic"
    if re.match(r"^https?://", t): return "naked_url"
    return "descriptive"

def analyze_anchors(soup, base_url=""):
    base_domain = urlparse(base_url).netloc if base_url else ""
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(base_url, href) if base_url else href
        anchor = a.get_text(strip=True)
        is_internal = urlparse(full).netloc == base_domain if base_domain else False
        is_image = bool(a.find("img"))
        nofollow = "nofollow" in a.get("rel", [])
        links.append({
            "url": full[:200], "anchor_text": anchor[:100],
            "is_internal": is_internal, "is_image_link": is_image,
            "nofollow": nofollow, "anchor_type": classify_anchor(anchor, is_image),
            "anchor_length": len(anchor),
        })
    return links

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.json
    url = data.get("url")
    if not url:
        return jsonify({"error": "No URL provided"}), 400
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        links = analyze_anchors(soup, url)
        from collections import Counter
        types = Counter(l["anchor_type"] for l in links)
        top_anchors = Counter(l["anchor_text"] for l in links if l["anchor_text"]).most_common(10)
        return jsonify({
            "total": len(links),
            "internal": sum(1 for l in links if l["is_internal"]),
            "external": sum(1 for l in links if not l["is_internal"]),
            "type_distribution": dict(types),
            "top_anchors": top_anchors,
            "links": links
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)