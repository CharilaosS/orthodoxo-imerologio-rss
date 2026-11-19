"""Ημερολόγιο Ορθοδοξίας — καθημερινό RSS post.

Πηγές:
  - https://agia-triada-panorama.gr : νηστεία, συναξαριστής, απόσπασμα π. Συμεών (το `active` της ημέρας)
  - https://www.saint.gr            : πρώτος άγιος της ημέρας (εικόνα + σύντομη βιογραφία)

Έξοδος (φάκελος docs/ → GitHub Pages): feed.xml, img/YYYY-MM-DD.jpg, icon.png
Ιστορικό: data/items.json (κρατά τις τελευταίες KEEP_DAYS μέρες).
"""
import html
import io
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timedelta
from email.utils import format_datetime
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE_URL = "https://charilaoss.github.io/orthodoxo-imerologio-rss"
ATP_URL = "https://agia-triada-panorama.gr"
SAINT_URL = "https://www.saint.gr"
FEED_TITLE = "Ημερολόγιο Ορθοδοξίας"
KEEP_DAYS = 14
TZ = ZoneInfo("Europe/Athens")

ROOT = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(ROOT, "docs")
IMG_DIR = os.path.join(DOCS, "img")
DATA = os.path.join(ROOT, "data", "items.json")
FONT_B = os.path.join(ROOT, "fonts", "FiraSansExtraCondensed-Bold.ttf")
FONT_R = os.path.join(ROOT, "fonts", "FiraSansExtraCondensed-Regular.ttf")

DAYS = ["Δευτέρα", "Τρίτη", "Τετάρτη", "Πέμπτη", "Παρασκευή", "Σάββατο", "Κυριακή"]
MONTHS_GEN = ["Ιανουαρίου", "Φεβρουαρίου", "Μαρτίου", "Απριλίου", "Μαΐου", "Ιουνίου",
              "Ιουλίου", "Αυγούστου", "Σεπτεμβρίου", "Οκτωβρίου", "Νοεμβρίου", "Δεκεμβρίου"]

BG, FG, GOLD, MUTED = (28, 28, 30), (214, 210, 200), (201, 162, 39), (150, 146, 138)


# ---------------------------------------------------------------- helpers
def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (RSS generator)"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", errors="replace")


def clean(s):
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(re.sub(r"[ \t\r]+", " ", s))
    return "\n".join(line.strip() for line in s.split("\n")).strip()


def up(s):
    """Κεφαλαία χωρίς τόνους/πνεύματα (σωστά ελληνικά κεφαλαία)."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return unicodedata.normalize("NFC", s).upper()


# ---------------------------------------------------------------- πηγές
def parse_atp(page):
    def active(cls):
        m = re.search(r"<p class='%s active'>(.*?)</p>" % cls, page, re.S)
        return re.sub(r"\s*\n\s*", " ", clean(m.group(1))) if m else ""

    blk = page[page.find("Ἀποσπάσματα ἀπό τούς λόγους"):]
    blk = blk[:blk.find('class="nav"')]
    m = re.search(r"<p class='active'>(.*?)</p>", blk, re.S)
    apo = [p for p in clean(m.group(1)).split("\n") if p] if m else []
    return {
        "celeb": active("celeb"),
        "period": active("period"),
        "nisteia": active("nisteia"),
        "apospasma": apo,
    }


def parse_saint(home):
    home = home[home.find("εορτάζουν:"):]
    saints = re.findall(
        r'href="(/\d+/saint\.aspx)".*?<img src="([^"]+)".*?</div>\s*(.*?)</a>', home, re.S)
    if not saints:
        raise RuntimeError("saint.gr: δεν βρέθηκαν άγιοι ημέρας")
    path, thumb, name = saints[0]
    url = SAINT_URL + path
    page = fetch(url)

    bio = []
    m = re.search(r'id="Biography"><p class="myReadMore">(.*?)</p>', page, re.S)
    if m:
        paras = [clean(p) for p in re.split(r"(?:<br\s*/?>\s*){2}", m.group(1))]
        n = 0
        for p in filter(None, paras):
            if n + len(p) > 750:
                cuts = [x.end() for x in re.finditer(r"[.;!»]\s", p + " ") if n + x.end() <= 750]
                if cuts:
                    bio.append(p[:cuts[-1]].strip())
                break
            bio.append(p)
            n += len(p)

    # εικόνα: η μεγάλη εκδοχή της μικρογραφίας του πρώτου αγίου
    img_url = None
    if "nophoto" not in thumb:
        big = re.sub(r"s\.jpg$", ".jpg", thumb)
        img_url = big if big in page else thumb
    return {"name": clean(name), "url": url, "img": img_url, "bio": bio}


# ---------------------------------------------------------------- εικόνα (B, τετράγωνη)
def make_image(day, d, month, nisteia, icon_bytes, out_path):
    fb = lambda s: ImageFont.truetype(FONT_B, s)
    fr = lambda s: ImageFont.truetype(FONT_R, s)
    B = Image.new("RGB", (1000, 1000), BG)
    if icon_bytes:
        src = Image.open(io.BytesIO(icon_bytes)).convert("RGB")
        bg = src.resize((1000, max(1000, int(1000 * src.height / src.width))))
        top = max(0, (bg.height - 750) // 2)
        bg = bg.crop((0, top, 1000, top + 750)).filter(ImageFilter.GaussianBlur(30))
        B.paste(bg.point(lambda v: int(v * 0.45)), (0, 0))
        r = min(900 / src.width, 720 / src.height)
        ic = src.resize((int(src.width * r), int(src.height * r)), Image.LANCZOS)
        B.paste(ic, ((1000 - ic.width) // 2, 15 + (720 - ic.height) // 2))
    else:  # χωρίς εικόνα αγίου: σταυρός
        draw_cross(ImageDraw.Draw(B), 500, 60, 0.62)
    dr = ImageDraw.Draw(B)
    dr.rectangle([(0, 750), (1000, 1000)], fill=BG)
    dr.line([(0, 750), (1000, 750)], fill=GOLD, width=4)
    num = str(d)
    dr.text((60, 765), num, font=fb(200), fill=FG)
    x = 60 + dr.textlength(num, font=fb(200)) + 34
    dr.text((x, 790), up(day), font=fb(56), fill=MUTED)
    dr.text((x, 848), up(month), font=fb(74), fill=FG)
    dr.text((x, 935), up(nisteia), font=fr(38), fill=GOLD)
    B.save(out_path, quality=86)


def draw_cross(dr, cx, top, k):
    g, w = GOLD, int(54 * k)
    y = lambda v: top + int(v * k)
    dr.rectangle([(cx - w // 2, y(0)), (cx + w // 2, y(690))], fill=g)
    dr.rectangle([(cx - int(120 * k), y(80)), (cx + int(120 * k), y(124))], fill=g)
    dr.rectangle([(cx - int(250 * k), y(200)), (cx + int(250 * k), y(200) + w)], fill=g)
    dr.polygon([(cx - int(165 * k), y(480)), (cx + int(165 * k), y(420)),
                (cx + int(165 * k), y(466)), (cx - int(165 * k), y(526))], fill=g)


def make_icon(path):
    S = 1024
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([(0, 0), (S, S)], radius=220, fill=(110, 22, 32))
    dr.rounded_rectangle([(40, 40), (S - 40, S - 40)], radius=190, outline=GOLD, width=10)
    draw_cross(dr, S // 2, 170, 1.0)
    im.resize((256, 256), Image.LANCZOS).save(path)


# ---------------------------------------------------------------- post
def build_item(now):
    e = html.escape
    day, month = DAYS[now.weekday()], MONTHS_GEN[now.month - 1]
    iso = now.date().isoformat()

    atp = parse_atp(fetch(ATP_URL))
    try:
        saint = parse_saint(fetch(SAINT_URL))
    except Exception as ex:  # saint.gr εκτός: post χωρίς άγιο
        print("saint.gr:", ex, file=sys.stderr)
        saint = None

    icon_bytes = None
    if saint and saint["img"]:
        try:
            icon_bytes = fetch(saint["img"], binary=True)
        except Exception as ex:
            print("εικόνα αγίου:", ex, file=sys.stderr)

    os.makedirs(IMG_DIR, exist_ok=True)
    make_image(day, now.day, month, atp["nisteia"], icon_bytes, os.path.join(IMG_DIR, f"{iso}.jpg"))
    img_abs = f"{BASE_URL}/img/{iso}.jpg"

    parts = [f"{day} {now.day}/{now.month}"]
    if saint:
        parts.append(saint["name"])
    if atp["nisteia"]:
        parts.append(atp["nisteia"])
    title = ", ".join(parts)

    desc = [f'<p><img src="{img_abs}" alt="{e(day)} {now.day} {e(month)}"></p>',
            f"<h2>{e(day)} {now.day} {e(month)} {now.year}</h2>"]
    if atp["nisteia"]:
        per = f" <em>· {e(atp['period'])}</em>" if atp["period"] else ""
        desc.append(f"<p><strong>🍽 Νηστεία:</strong> {e(atp['nisteia'])}{per}</p>")
    if atp["celeb"]:
        desc.append(f"<h3>📖 Συναξαριστής</h3><p>{e(atp['celeb'])}</p>")
    if atp["apospasma"]:
        body = "".join(f"<p>{e(p)}</p>" for p in atp["apospasma"])
        desc.append(f"<h3>✝ Ἀποσπάσματα ἀπό τούς λόγους τοῦ π. Συμεών</h3><blockquote>{body}</blockquote>")
    if saint:
        desc.append(f"<h3>🕯 {e(saint['name'])}</h3>")
        desc += [f"<p>{e(p)}</p>" for p in saint["bio"]]
        desc.append(f'<p><a href="{saint["url"]}">Διαβάστε περισσότερα για {e(saint["name"])} στο saint.gr →</a></p>')

    return {
        "date": iso,
        "title": title,
        "link": saint["url"] if saint else ATP_URL,
        "image": img_abs,
        "pubDate": format_datetime(now.replace(hour=5, minute=0, second=0, microsecond=0)),
        "html": "\n".join(desc),
    }


def write_feed(items):
    e = html.escape
    out = []
    for it in items:
        out.append(f"""  <item>
    <title>{e(it['title'])}</title>
    <link>{e(it['link'])}</link>
    <guid isPermaLink="false">orthodoxo-imerologio-{it['date']}</guid>
    <pubDate>{it['pubDate']}</pubDate>
    <media:content url="{it['image']}" medium="image" type="image/jpeg" width="1000" height="1000"/>
    <media:thumbnail url="{it['image']}"/>
    <enclosure url="{it['image']}" type="image/jpeg" length="0"/>
    <description><![CDATA[{it['html']}]]></description>
    <content:encoded><![CDATA[{it['html']}]]></content:encoded>
  </item>""")
    last = items[0]["pubDate"] if items else format_datetime(datetime.now(TZ))
    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{FEED_TITLE}</title>
  <link>{ATP_URL}</link>
  <atom:link href="{BASE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
  <description>Νηστεία, Συναξαριστής, λόγοι π. Συμεών και ο άγιος της ημέρας</description>
  <language>el</language>
  <lastBuildDate>{last}</lastBuildDate>
  <image><url>{BASE_URL}/icon.png</url><title>{FEED_TITLE}</title><link>{ATP_URL}</link></image>
{chr(10).join(out)}
</channel>
</rss>
"""
    with open(os.path.join(DOCS, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(rss)


def main():
    now = datetime.now(TZ)
    items = []
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            items = json.load(f)

    new = build_item(now)
    items = [new] + [it for it in items if it["date"] != new["date"]]
    cutoff = (now.date() - timedelta(days=KEEP_DAYS - 1)).isoformat()
    items = [it for it in items if it["date"] >= cutoff]
    items.sort(key=lambda it: it["date"], reverse=True)

    keep = {f"{it['date']}.jpg" for it in items}
    for fn in os.listdir(IMG_DIR):
        if fn.endswith(".jpg") and fn not in keep:
            os.remove(os.path.join(IMG_DIR, fn))

    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)
    if not os.path.exists(os.path.join(DOCS, "icon.png")):
        make_icon(os.path.join(DOCS, "icon.png"))
    write_feed(items)
    print(new["title"])


if __name__ == "__main__":
    main()
