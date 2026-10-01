// Fills the Download section from the image index on the update server (R2), and Latest
// issues from the GitHub API (unauthenticated, 60 requests an hour per visitor).
const REPO = "kettlelinux/kettlelinux";
const DOWNLOADS = "https://updates.kettlelinux.org";
const API = `https://api.github.com/repos/${REPO}`;
const ISSUE_COUNT = 8;

function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

function size(bytes) {
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
  return `${bytes.toFixed(i > 1 ? 1 : 0)} ${units[i]}`;
}

function ago(iso) {
  const s = (Date.now() - new Date(iso)) / 1000;
  for (const [unit, secs] of [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (s >= secs) {
      const n = Math.floor(s / secs);
      return `${n} ${unit}${n > 1 ? "s" : ""} ago`;
    }
  }
  return "just now";
}

async function get(path) {
  const res = await fetch(API + path, { headers: { Accept: "application/vnd.github+json" } });
  if (!res.ok) throw new Error(`GitHub API ${res.status}`);
  return res.json();
}

// Release notes as upload-image.sh stores them: "## " headings, "- " bullets, plain lines
function renderNotes(text) {
  const box = el("div", { className: "notes" }, el("h4", { textContent: "Release notes" }));
  let list = null;
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!list) box.append(list = el("ul"));
      list.append(el("li", { textContent: line.slice(2) }));
      continue;
    }
    list = null;
    if (!line) continue;
    box.append(line.startsWith("#")
      ? el("h5", { textContent: line.replace(/^#+\s*/, "") })
      : el("p", { textContent: line }));
  }
  return box;
}

// Devices in the order the Download section lists them; names for index entries made before
// upload-image.sh recorded each image's model. A device not named here is listed after these.
const DEVICES = { odin2portal: "AYN Odin 2 Portal", thor: "AYN Thor", rp5: "Retroid Pocket 5" };

function releaseCard(img, older) {
  const head = el("div", { className: "release-head" },
    el("h3", { textContent: img.model || DEVICES[img.variant] || img.variant }),
    el("span", { className: "muted small", textContent:
      `Kettle ${img.version} (${img.buildid})${img.branch ? " · " + img.branch : ""} · ${new Date(img.date).toLocaleDateString()}` }));
  const assets = el("ul", { className: "assets" },
    el("li", {},
      el("a", { className: "btn primary", href: `${DOWNLOADS}/${img.file}`, textContent: `${img.name}.img.xz` }),
      el("span", { className: "muted small", textContent:
        `${size(img.size)}${img.image_size ? `, ${size(img.image_size)} unpacked` : ""}` })),
    el("li", {},
      el("a", { className: "btn", href: `${DOWNLOADS}/${img.sums}`, textContent: "SHA-256 checksums" })));
  const parts = [head, assets, el("p", { className: "small sha" }, "SHA-256: ", el("code", { textContent: img.sha256 }))];
  if (older.length) {
    parts.push(el("p", { className: "small" }, "Older: ", ...older.flatMap((o, i) => [
      i ? " · " : "", el("a", { href: `${DOWNLOADS}/${o.file}`, textContent: o.buildid })])));
  }
  if (img.notes) parts.push(renderNotes(img.notes));
  return el("div", { className: "card release" }, ...parts);
}

async function loadRelease() {
  const box = document.getElementById("release");
  try {
    // written by scripts/upload-image.sh, every device's images, newest first
    const res = await fetch(`${DOWNLOADS}/downloads/releases.json`, { cache: "no-cache" });
    if (!res.ok && res.status !== 404) throw new Error(`downloads ${res.status}`);
    const images = res.ok ? (await res.json()).images : [];
    if (!images.length) {
      box.replaceChildren(el("div", { className: "card" },
        el("p", {}, "No image has been released yet. You can ",
          el("a", { href: `https://github.com/${REPO}/wiki/Building`, textContent: "build one from source" }),
          " in the meantime.")));
      return;
    }
    const byDevice = new Map();
    for (const img of images) {
      if (!byDevice.has(img.variant)) byDevice.set(img.variant, []);
      byDevice.get(img.variant).push(img);
    }
    const order = Object.keys(DEVICES);
    const rank = v => (order.includes(v) ? order.indexOf(v) : order.length);
    const devices = [...byDevice.keys()].sort((a, b) => rank(a) - rank(b));
    box.replaceChildren(...devices.map(v => {
      const [img, ...older] = byDevice.get(v);
      return releaseCard(img, older);
    }));
  } catch (e) {
    box.replaceChildren(el("div", { className: "card" },
      el("p", {}, "Couldn't load the download list. Try again later, or ask in the ",
        el("a", { href: `https://github.com/${REPO}/issues`, textContent: "issue tracker" }), ".")));
  }
}

async function loadIssues() {
  const list = document.getElementById("issue-list");
  try {
    // the issues endpoint includes pull requests; ask for extra and drop them
    const items = await get(`/issues?state=open&sort=created&direction=desc&per_page=${ISSUE_COUNT * 2}`);
    const issues = items.filter(i => !i.pull_request).slice(0, ISSUE_COUNT);
    if (!issues.length) {
      list.replaceChildren(el("li", { className: "muted", textContent: "No open issues." }));
      return;
    }
    list.replaceChildren(...issues.map(i => {
      const labels = i.labels.map(l => {
        const s = el("span", { className: "label", textContent: l.name });
        s.style.color = s.style.borderColor = `#${l.color}`;
        return s;
      });
      return el("li", {},
        el("span", { className: "dot" }),
        el("a", { className: "title", href: i.html_url, textContent: i.title }),
        ...labels,
        el("div", { className: "meta", textContent: `#${i.number} opened ${ago(i.created_at)} by ${i.user.login}` +
          (i.comments ? ` · ${i.comments} comment${i.comments > 1 ? "s" : ""}` : "") }));
    }));
  } catch (e) {
    list.replaceChildren(el("li", {}, "Couldn't load issues. ",
      el("a", { href: `https://github.com/${REPO}/issues`, textContent: "See them on GitHub" }), "."));
  }
}

loadRelease();
loadIssues();
