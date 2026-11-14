"""Build web/slides.html: a standalone, animated copy of the pitch deck (6 slides, keyboard + click).

Usage: python3 scripts/build_slides.py <deck project folder> <problem-slide photo .jpg>
The deck folder holds deck.json, deck.css and slides/*.html, as exported from the Slides artifact.
"""
import base64, json, pathlib, re, sys

deck = pathlib.Path(sys.argv[1]); photo = pathlib.Path(sys.argv[2])
out = pathlib.Path(__file__).resolve().parent.parent / "web" / "slides.html"
cfg = json.loads((deck / "deck.json").read_text())
css = (deck / "deck.css").read_text()

ICONS = {  # simple line icons for the <x-icon> tags the Slides type normally renders
    "Clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "Book": '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5M8 7h7"/>',
    "Search": '<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    "Chat": '<path d="M4 5h16v11H9l-5 4z"/>',
}
def icon(m):
    p = ICONS[m.group(1)]
    return ('<x-icon name="%s"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg></x-icon>') % (m.group(1), p)

photo_uri = "data:image/jpeg;base64," + base64.b64encode(photo.read_bytes()).decode()
slides = []
for sid in cfg["order"]:
    h = (deck / "slides" / f"{sid}.html").read_text()
    h = re.sub(r'<x-icon name="(\w+)"></x-icon>', icon, h)
    h = re.sub(r'src="/_blob/[0-9a-f]+"', f'src="{photo_uri}"', h)
    h = h.replace('<section ', '<section data-slide ', 1)
    slides.append(h)

page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MedGuard · Pitch</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700&family=Source+Sans+3:wght@400;600&display=swap">
<style>
* { margin: 0; box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; background: #0B0F19; }
#deck { position: absolute; left: 0; top: 0; width: 1920px; height: 1080px; transform-origin: 0 0; }
#deck > section { position: absolute; inset: 0; width: 1920px; height: 1080px; visibility: hidden; }
#deck > section.on { visibility: visible; }
#deck > section:not(.on) * { animation-play-state: paused !important; }
aside { display: none; }
x-icon { display: inline-block; flex: none; }
x-icon svg { display: block; width: 100%; height: 100%; }
a { cursor: pointer; }
#hud { position: fixed; right: 14px; bottom: 10px; font: 600 13px 'Source Sans 3', Arial, sans-serif; color: rgba(140,150,170,.75); user-select: none; }
/* ---- deck.css ---- */
""" + css + """
</style>
</head>
<body>
<div id="deck">
""" + "\n".join(slides) + """
</div>
<div id="hud"></div>
<script>
(function () {
  var deck = document.getElementById("deck"), hud = document.getElementById("hud");
  var all = Array.prototype.slice.call(deck.querySelectorAll("section[data-slide]"));
  var cur = 0;
  function fit() {
    var s = Math.min(window.innerWidth / 1920, window.innerHeight / 1080);
    deck.style.transform = "scale(" + s + ")";
    deck.style.left = (window.innerWidth - 1920 * s) / 2 + "px";
    deck.style.top = (window.innerHeight - 1080 * s) / 2 + "px";
  }
  function show(i) {
    cur = Math.max(0, Math.min(all.length - 1, i));
    all.forEach(function (el, k) {
      if (k === cur) {                       // replay the entrance animations each time a slide opens
        var fresh = el.cloneNode(true); fresh.classList.add("on");
        el.parentNode.replaceChild(fresh, el); all[k] = fresh;
      } else el.classList.remove("on");
    });
    hud.textContent = (cur + 1) + " / " + all.length + "  ·  ← →  ·  F full screen";
    if (location.hash !== "#" + (cur + 1)) history.replaceState(null, "", "#" + (cur + 1));
  }
  window.addEventListener("keydown", function (e) {
    var k = e.key;
    if (k === "ArrowRight" || k === "PageDown" || k === " " || k === "Enter" || k === "ArrowDown") { e.preventDefault(); show(cur + 1); }
    else if (k === "ArrowLeft" || k === "PageUp" || k === "ArrowUp" || k === "Backspace") { e.preventDefault(); show(cur - 1); }
    else if (k === "Home") show(0);
    else if (k === "End") show(all.length - 1);
    else if (k === "f" || k === "F") { if (!document.fullscreenElement) document.documentElement.requestFullscreen().catch(function () {}); else document.exitFullscreen(); }
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest("a")) return;       // links open the demo, they don't change slides
    show(e.clientX < window.innerWidth / 4 ? cur - 1 : cur + 1);
  });
  window.addEventListener("resize", fit);
  fit();
  show((parseInt(location.hash.slice(1), 10) || 1) - 1);
})();
</script>
</body>
</html>
"""
out.write_text(page)
print(out, len(page) // 1024, "KB")
