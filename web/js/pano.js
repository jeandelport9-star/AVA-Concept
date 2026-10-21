// WebGL 360 panorama viewer with item outlines, links to other setups and a
// box tool for marking items by hand. Conventions match engine/geometry.py:
// yaw 0 = image centre, positive right; pitch positive up (degrees).
const D2R = Math.PI / 180;
const wrap = a => ((a + 540) % 360) - 180;

export class PanoViewer {
  constructor(container, { onBox, onLink, onMark, onView, onTag, onPin } = {}) {
    this.el = container;
    this.cb = { onBox, onLink, onMark, onView, onTag, onPin };
    this.cam = { yaw: 0, pitch: 0, fov: 90 };
    this.boxes = []; this.links = []; this.pins = []; this.hits = [];
    this.markMode = false; this.anim = null; this.dirty = true; this.ready = false;
    container.innerHTML = '<canvas class="gl" tabindex="0" aria-label="360 view. Drag to look around, scroll to zoom."></canvas><canvas class="ov"></canvas>' +
      '<div class="loading" style="position:absolute;inset:0;display:grid;place-items:center;color:#cfd8d4;pointer-events:none">No panorama</div>';
    this.cv = container.querySelector('.gl'); this.ov = container.querySelector('.ov');
    this.ov.style.pointerEvents = 'none';
    this.ctx = this.ov.getContext('2d');
    this.msg = container.querySelector('.loading');
    this._gl();
    this._input();
    this.ro = new ResizeObserver(() => this._resize()); this.ro.observe(container);
    this._resize();
    const loop = t => { if (this.dead) return; this._frame(t); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }
  destroy() { this.dead = true; this.ro.disconnect(); }

  _gl() {
    const gl = this.gl = this.cv.getContext('webgl', { antialias: false });
    if (!gl) { this.msg.textContent = 'WebGL is not available in this browser.'; return; }
    this.maxTex = gl.getParameter(gl.MAX_TEXTURE_SIZE);
    const sh = (t, s) => { const o = gl.createShader(t); gl.shaderSource(o, s); gl.compileShader(o); return o; };
    const p = this.prog = gl.createProgram();
    gl.attachShader(p, sh(gl.VERTEX_SHADER, 'attribute vec2 a;varying vec2 v;void main(){v=a;gl_Position=vec4(a,0.,1.);}'));
    gl.attachShader(p, sh(gl.FRAGMENT_SHADER, `precision highp float;varying vec2 v;uniform sampler2D T;uniform float yaw,pitch,tanH,aspect;
      void main(){vec3 d=normalize(vec3(v.x*tanH,v.y*tanH/aspect,1.));float cp=cos(pitch),sp=sin(pitch),cy=cos(yaw),sy=sin(yaw);
      float y1=cp*d.y+sp*d.z,z1=-sp*d.y+cp*d.z;float x2=cy*d.x+sy*z1,z2=-sy*d.x+cy*z1;
      gl_FragColor=texture2D(T,vec2(fract(atan(x2,z2)/6.2831853+.5),.5-asin(clamp(y1,-1.,1.))/3.1415927));}`));
    gl.linkProgram(p); gl.useProgram(p);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(p, 'a'); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    this.tex = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, this.tex);
    for (const [k, v] of [[gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE], [gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE], [gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR]])
      gl.texParameteri(gl.TEXTURE_2D, k, v);
    this.u = n => gl.getUniformLocation(p, n);
  }

  load(url) {
    if (url === this.url) return Promise.resolve();
    this.url = url; this.ready = false; this.msg.hidden = false; this.msg.textContent = 'Loading panorama…';
    return new Promise(res => {
      const im = new Image();
      im.onload = () => {
        if (this.url !== url) return res();
        let src = im;
        if (im.width > this.maxTex) { const c = document.createElement('canvas'); c.width = this.maxTex; c.height = this.maxTex / 2; c.getContext('2d').drawImage(im, 0, 0, c.width, c.height); src = c; }
        const gl = this.gl; gl.bindTexture(gl.TEXTURE_2D, this.tex); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, src);
        this.ready = true; this.msg.hidden = true; this.dirty = true; res();
      };
      im.onerror = () => { this.msg.textContent = 'Could not load the panorama.'; res(); };
      im.src = url;
    });
  }

  lookAt(t, instant) {
    const from = { ...this.cam }, dy = wrap(t.yaw - this.cam.yaw), t0 = performance.now();
    const dur = instant || matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 550;
    this.anim = now => {
      const k = dur ? Math.min(1, (now - t0) / dur) : 1, e = k < .5 ? 2 * k * k : 1 - (-2 * k + 2) ** 2 / 2;
      this.cam.yaw = wrap(from.yaw + dy * e); this.cam.pitch = from.pitch + ((t.pitch ?? 0) - from.pitch) * e;
      this.cam.fov = from.fov + ((t.fov ?? from.fov) - from.fov) * e;
      if (k >= 1) this.anim = null;
    };
    this.dirty = true;
  }
  setBoxes(b) { this.boxes = b; this.dirty = true; }
  setLinks(l) { this.links = l; this.dirty = true; }
  setMarkMode(on) { this.markMode = on; this.tagMode = false; this.cv.style.cursor = on ? 'crosshair' : 'grab'; }
  setTagMode(on) { this.tagMode = on; this.markMode = false; this.cv.style.cursor = on ? 'crosshair' : 'grab'; }
  setPins(p) { this.pins = p; this.dirty = true; }

  _resize() {
    const r = this.el.getBoundingClientRect(); this.dpr = Math.min(devicePixelRatio || 1, 2);
    this.W = Math.max(1, r.width); this.H = Math.max(1, r.height);
    for (const c of [this.cv, this.ov]) { c.width = Math.round(this.W * this.dpr); c.height = Math.round(this.H * this.dpr); }
    this.gl?.viewport(0, 0, this.cv.width, this.cv.height); this.dirty = true;
  }

  project(yw, pw) {
    const y = yw * D2R, p = pw * D2R, a = this.cam.yaw * D2R, b = this.cam.pitch * D2R;
    const x = Math.cos(p) * Math.sin(y), yy = Math.sin(p), z = Math.cos(p) * Math.cos(y);
    const x1 = Math.cos(a) * x - Math.sin(a) * z, z1 = Math.sin(a) * x + Math.cos(a) * z;
    const y2 = Math.cos(b) * yy - Math.sin(b) * z1, z2 = Math.sin(b) * yy + Math.cos(b) * z1;
    if (z2 < .06) return null;
    const tanH = Math.tan(this.cam.fov * D2R / 2), asp = this.W / this.H;
    return [(x1 / z2 / tanH + 1) / 2 * this.W, (1 - y2 / z2 / (tanH / asp)) / 2 * this.H];
  }
  unproject(px, py) {
    const tanH = Math.tan(this.cam.fov * D2R / 2), asp = this.W / this.H;
    const vx = px / this.W * 2 - 1, vy = 1 - py / this.H * 2;
    let d = [vx * tanH, vy * tanH / asp, 1]; const n = Math.hypot(...d); d = d.map(v => v / n);
    const cp = Math.cos(this.cam.pitch * D2R), sp = Math.sin(this.cam.pitch * D2R), cy = Math.cos(this.cam.yaw * D2R), sy = Math.sin(this.cam.yaw * D2R);
    const y1 = cp * d[1] + sp * d[2], z1 = -sp * d[1] + cp * d[2], x2 = cy * d[0] + sy * z1, z2 = -sy * d[0] + cy * z1;
    return { yaw: Math.atan2(x2, z2) / D2R, pitch: Math.asin(Math.max(-1, Math.min(1, y1))) / D2R };
  }

  _input() {
    const c = this.cv; let drag = null; const pts = new Map();
    c.addEventListener('pointerdown', e => {
      c.setPointerCapture(e.pointerId); pts.set(e.pointerId, e); this.anim = null;
      drag = { x: e.clientX, y: e.clientY, yaw: this.cam.yaw, pitch: this.cam.pitch, fov: this.cam.fov, moved: 0, d0: null, mark: this.markMode };
    });
    c.addEventListener('pointermove', e => {
      if (!drag) return; pts.set(e.pointerId, e);
      const r = c.getBoundingClientRect();
      if (drag.mark) { drag.moved = 9; drag.cur = [e.clientX - r.left, e.clientY - r.top]; drag.start ??= [drag.x - r.left, drag.y - r.top]; this.dirty = true; this.rubber = drag; return; }
      if (pts.size === 2) { const [a, b] = [...pts.values()]; const d = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY); drag.d0 ??= d;
        this.cam.fov = Math.min(110, Math.max(20, drag.fov * drag.d0 / d)); drag.moved = 99; this.dirty = true; return; }
      const k = this.cam.fov / this.W, dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      drag.moved = Math.max(drag.moved, Math.abs(dx) + Math.abs(dy));
      this.cam.yaw = wrap(drag.yaw - dx * k); this.cam.pitch = Math.max(-85, Math.min(85, drag.pitch + dy * k)); this.dirty = true;
    });
    const end = e => {
      pts.delete(e.pointerId);
      if (drag?.mark && drag.cur && e.type === 'pointerup') {
        const [x0, y0] = drag.start, [x1, y1] = drag.cur;
        if (Math.abs(x1 - x0) > 6 && Math.abs(y1 - y0) > 6) {
          const pts4 = [[Math.min(x0, x1), Math.min(y0, y1)], [Math.max(x0, x1), Math.min(y0, y1)], [Math.min(x0, x1), Math.max(y0, y1)], [Math.max(x0, x1), Math.max(y0, y1)],
            [(x0 + x1) / 2, Math.min(y0, y1)], [(x0 + x1) / 2, Math.max(y0, y1)]].map(([x, y]) => this.unproject(x, y));
          const ref = pts4[0].yaw, rel = pts4.map(p => ref + wrap(p.yaw - ref));
          this.cb.onMark?.({ yaw_l: Math.min(...rel), yaw_r: Math.max(...rel), pitch_top: Math.max(...pts4.map(p => p.pitch)), pitch_bot: Math.min(...pts4.map(p => p.pitch)) });
        }
        this.rubber = null; this.dirty = true;
      } else if (drag && drag.moved < 5 && e.type === 'pointerup') {
        if (this.tagMode) { const r = this.cv.getBoundingClientRect(); this.cb.onTag?.(this.unproject(e.clientX - r.left, e.clientY - r.top)); }
        else this._hit(e);
      }
      if (!pts.size) drag = null;
    };
    c.addEventListener('pointerup', end); c.addEventListener('pointercancel', end);
    c.addEventListener('pointermove', e => {          // highlight the disc under the mouse
      if (drag) return;
      const r = c.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
      const h = this.hits.find(k => k.kind === 'link' && x >= k.x0 && x <= k.x1 && y >= k.y0 && y <= k.y1);
      const id = h ? h.id : null;
      if (id !== this.hover) { this.hover = id; this.dirty = true; c.style.cursor = id ? 'pointer' : (this.markMode || this.tagMode ? 'crosshair' : 'grab'); }
    });
    c.addEventListener('wheel', e => { e.preventDefault(); this.cam.fov = Math.min(110, Math.max(20, this.cam.fov * Math.exp(e.deltaY * .0012))); this.dirty = true; }, { passive: false });
    c.addEventListener('keydown', e => {
      const s = { ArrowLeft: [-8, 0], ArrowRight: [8, 0], ArrowUp: [0, 6], ArrowDown: [0, -6] }[e.key];
      if (s) { e.preventDefault(); e.stopPropagation(); this.cam.yaw = wrap(this.cam.yaw + s[0]); this.cam.pitch = Math.max(-85, Math.min(85, this.cam.pitch + s[1])); this.dirty = true; }
    });
  }
  _hit(e) {
    const r = this.cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    const h = this.hits.filter(k => x >= k.x0 && x <= k.x1 && y >= k.y0 && y <= k.y1).sort((a, b) => (a.x1 - a.x0) * (a.y1 - a.y0) - (b.x1 - b.x0) * (b.y1 - b.y0))[0];
    if (h?.kind === 'link') this.cb.onLink?.(h.id); else if (h?.kind === 'pin') this.cb.onPin?.(h.id); else if (h) this.cb.onBox?.(h.id);
  }

  _frame(now) {
    if (this.anim) { this.anim(now); this.dirty = true; }
    if (!this.dirty) return;
    this.dirty = false;
    const gl = this.gl;
    if (gl && this.ready) {
      gl.uniform1f(this.u('yaw'), this.cam.yaw * D2R); gl.uniform1f(this.u('pitch'), this.cam.pitch * D2R);
      gl.uniform1f(this.u('tanH'), Math.tan(this.cam.fov * D2R / 2)); gl.uniform1f(this.u('aspect'), this.W / this.H);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    this._overlay();
    this.cb.onView?.(this.cam);
  }
  _overlay() {
    const ctx = this.ctx; ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0); ctx.clearRect(0, 0, this.W, this.H); this.hits = [];
    if (!this.ready) return;
    // navigation: a disc lying on the ground at each nearby viewpoint (like Matterport / Street View)
    const far = [...this.links].sort((a, b) => b.dist - a.dist);
    for (const l of far) {
      const P = (l.ring || []).map(([y, p]) => this.project(y, p));
      if (!P.length || P.some(v => !v)) continue;
      const xs = P.map(v => v[0]), ys = P.map(v => v[1]);
      const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
      if (x1 - x0 < 6) continue;
      const hot = this.hover === l.id;
      ctx.beginPath(); P.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath();
      ctx.fillStyle = hot ? 'rgba(255,255,255,.45)' : 'rgba(255,255,255,.18)'; ctx.fill();
      ctx.lineWidth = hot ? 3 : 2; ctx.strokeStyle = 'rgba(255,255,255,.9)'; ctx.stroke();
      const inner = (l.inner || []).map(([y, p]) => this.project(y, p));
      if (inner.length && inner.every(Boolean)) {
        ctx.beginPath(); inner.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath();
        ctx.fillStyle = 'rgba(255,255,255,.85)'; ctx.fill();
      }
      if (hot || l.dist < 4) {
        ctx.font = '500 12px "IBM Plex Mono", monospace'; ctx.textAlign = 'center';
        const tw = ctx.measureText(l.label).width + 10, cx = (x0 + x1) / 2;
        ctx.fillStyle = 'rgba(10,16,15,.7)'; ctx.fillRect(cx - tw / 2, y0 - 22, tw, 17); ctx.fillStyle = '#fff'; ctx.fillText(l.label, cx, y0 - 9);
      }
      this.hits.push({ kind: 'link', id: l.id, x0, x1, y0: y0 - 4, y1: y1 + 4 });
    }
    for (const b of this.boxes) {
      const P = [], n = 10;
      for (let i = 0; i <= n; i++) P.push([b.l + (b.r - b.l) * i / n, b.t]);
      for (let i = 0; i <= n; i++) P.push([b.r, b.t + (b.b - b.t) * i / n]);
      for (let i = 0; i <= n; i++) P.push([b.r - (b.r - b.l) * i / n, b.b]);
      for (let i = 0; i <= n; i++) P.push([b.l, b.b + (b.t - b.b) * i / n]);
      const S = P.map(([y, p]) => this.project(y, p)); if (S.some(v => !v)) continue;
      ctx.beginPath(); S.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)); ctx.closePath();
      ctx.lineWidth = b.selected ? 3.5 : 2; ctx.strokeStyle = b.color; ctx.setLineDash(b.dashed ? [6, 4] : []); ctx.stroke(); ctx.setLineDash([]);
      if (b.selected) { ctx.globalAlpha = .14; ctx.fillStyle = b.color; ctx.fill(); ctx.globalAlpha = 1; }
      const xs = S.map(v => v[0]), ys = S.map(v => v[1]), x0 = Math.min(...xs), y0 = Math.min(...ys);
      ctx.font = '600 12px "IBM Plex Mono", monospace'; const tw = ctx.measureText(b.label).width + 10;
      ctx.fillStyle = b.color; ctx.fillRect(x0, y0 - 19, tw, 18); ctx.fillStyle = '#fff'; ctx.textAlign = 'left'; ctx.fillText(b.label, x0 + 5, y0 - 6);
      this.hits.push({ kind: 'box', id: b.id, x0, x1: Math.max(...xs, x0 + tw), y0: y0 - 19, y1: Math.max(...ys) });
    }
    for (const p of this.pins) {       // hand-placed tags: a pin with a short label
      const c = this.project(p.yaw, p.pitch); if (!c) continue;
      const [x, y] = c;
      ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x - 7, y - 16); ctx.arc(x, y - 22, 9, Math.PI * .8, Math.PI * .2); ctx.lineTo(x, y); ctx.closePath();
      ctx.fillStyle = p.color; ctx.fill(); ctx.lineWidth = p.selected ? 3 : 1.5; ctx.strokeStyle = '#fff'; ctx.stroke();
      ctx.beginPath(); ctx.arc(x, y - 22, 3.2, 0, Math.PI * 2); ctx.fillStyle = '#fff'; ctx.fill();
      ctx.font = '600 12px "IBM Plex Mono", monospace'; const tw = ctx.measureText(p.label).width + 10;
      ctx.fillStyle = 'rgba(10,16,15,.78)'; ctx.fillRect(x + 12, y - 32, tw, 18); ctx.fillStyle = '#fff'; ctx.textAlign = 'left'; ctx.fillText(p.label, x + 17, y - 19);
      this.hits.push({ kind: 'pin', id: p.id, x0: x - 10, x1: x + 12 + tw, y0: y - 34, y1: y + 2 });
    }
    if (this.rubber?.cur) {
      const [x0, y0] = this.rubber.start, [x1, y1] = this.rubber.cur;
      ctx.setLineDash([5, 4]); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.strokeRect(x0, y0, x1 - x0, y1 - y0); ctx.setLineDash([]);
    }
  }
}

/** Viewpoints near this one, as discs on the ground. The camera height only
 *  sets how far below the horizon the ground is; any height (or the floor) works. */
export function setupLinks(cur, setups, mpp, camH = 1.5, maxM = 8, maxN = 8) {
  camH = Math.max(.3, camH || 1.5);
  const near = setups.filter(o => o.id !== cur.id && o.capture_id === cur.capture_id)
    .map(o => ({ o, d: Math.hypot(o.x - cur.x, o.y - cur.y) * mpp }))
    .filter(x => x.d >= .4 && x.d <= maxM).sort((a, b) => a.d - b.d).slice(0, maxN);
  const toAng = (dx, dy) => {           // ground point (metres east, south of the camera) -> yaw / pitch in this panorama
    const d = Math.hypot(dx, dy), bearing = Math.atan2(dx, -dy) / D2R;
    return [wrap(bearing + cur.forward - cur.travel), -Math.atan2(camH, d) / D2R];
  };
  return near.map(({ o, d }) => {
    const ex = (o.x - cur.x) * mpp, ey = (o.y - cur.y) * mpp, R = Math.min(.45, .12 + d * .05);
    const ring = [], inner = [];
    for (let k = 0; k < 24; k++) {
      const a = k / 24 * 2 * Math.PI;
      ring.push(toAng(ex + R * Math.cos(a), ey + R * Math.sin(a)));
      inner.push(toAng(ex + R * .3 * Math.cos(a), ey + R * .3 * Math.sin(a)));
    }
    // keep each ring continuous across the +-180 seam
    const fix = pts => { const y0 = pts[0][0]; return pts.map(([y, p]) => [y0 + wrap(y - y0), p]); };
    const [yaw, pitch] = toAng(ex, ey);
    return { id: o.id, label: `${o.name || o.id} · ${d.toFixed(1)} m`, yaw, pitch, dist: d, ring: fix(ring), inner: fix(inner) };
  });
}
