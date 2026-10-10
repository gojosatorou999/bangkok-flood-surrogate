const KEY_TO_LABEL = {
  "1": "NORMAL",
  "2": "WATERLOGGING",
  "3": "FLOODING",
  "4": "SEVERE_FLOODING",
  "0": "UNUSABLE",
  "o": "OCCLUDED",
};

let current = null;
let roiMode = false;
let roiPoints = [];

function labeller() {
  return document.getElementById("labellerInput").value.trim() || "anon";
}

async function loadNext() {
  const res = await fetch(`/api/next?labeller=${encodeURIComponent(labeller())}`);
  const img = document.getElementById("frame");
  if (!res.ok) {
    current = null;
    img.removeAttribute("src");
    img.alt = "no more frames to label";
    document.getElementById("meta").textContent = "";
    return;
  }
  current = await res.json();
  img.src = current.frame_url;
  img.alt = current.cam_id;
  document.getElementById("meta").textContent =
    `${current.cam_id} @ ${current.ts_utc} (zero-shot: ${current.zeroshot_class || "?"})`;
  roiPoints = [];
  drawRoi();
}

async function sendLabel(label) {
  if (!current) return;
  await fetch("/api/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cam_id: current.cam_id,
      ts_utc: current.ts_utc,
      sha1: current.sha1,
      label,
      labeller: labeller(),
    }),
  });
  await refreshProgress();
  await loadNext();
}

async function undo() {
  await fetch("/api/undo", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ labeller: labeller() }),
  });
  await refreshProgress();
}

async function refreshProgress() {
  const res = await fetch(`/api/progress?labeller=${encodeURIComponent(labeller())}`);
  const counts = await res.json();
  document.getElementById("progress").textContent = Object.entries(counts)
    .map(([k, v]) => `${k}: ${v}`)
    .join("   ");
}

function drawRoi() {
  const canvas = document.getElementById("roiCanvas");
  const img = document.getElementById("frame");
  canvas.width = img.clientWidth;
  canvas.height = img.clientHeight;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!roiPoints.length) return;
  ctx.strokeStyle = "#0f0";
  ctx.lineWidth = 2;
  ctx.beginPath();
  roiPoints.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  if (roiPoints.length > 2) ctx.closePath();
  ctx.stroke();
}

document.getElementById("stage").addEventListener("click", (e) => {
  if (!roiMode || !current) return;
  const rect = document.getElementById("frame").getBoundingClientRect();
  roiPoints.push([Math.round(e.clientX - rect.left), Math.round(e.clientY - rect.top)]);
  drawRoi();
});

window.addEventListener("keydown", async (e) => {
  const target = e.target;
  if (target && target.id === "labellerInput") return; // typing a name shouldn't trigger labels

  const k = e.key;
  if (k === "r") {
    roiMode = !roiMode;
    document.getElementById("roiMode").textContent = roiMode ? "(on, click points)" : "";
    if (!roiMode && roiPoints.length >= 3 && current) {
      await fetch("/api/roi", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cam_id: current.cam_id, points: roiPoints }),
      });
    }
    return;
  }
  if (k === "s") {
    await loadNext();
    return;
  }
  if (k === "z") {
    await undo();
    return;
  }
  if (KEY_TO_LABEL[k]) {
    await sendLabel(KEY_TO_LABEL[k]);
  }
});

refreshProgress();
loadNext();
