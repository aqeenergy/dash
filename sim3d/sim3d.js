// SIMULATIONS · Section 02 — 3D cabin fire simulator for FLAMA.
// Three.js viewer + lightweight stable-fluids advection–diffusion engine.
// Data with provenance comes from #sim3d-data (built read-only from base_de_datos by sim3d_data.py).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const DATA = JSON.parse(document.getElementById("sim3d-data").textContent);
const $ = (id) => document.getElementById(id);
const root = $("s3-root");
const section = document.getElementById("sim-sec-2");
const REDUCED = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

// ---------------------------------------------------------------------------
// Colormap (blue → cyan → yellow → orange → red), shared by heat map + legend
// ---------------------------------------------------------------------------
const STOPS = [[0, 0x12306e], [0.2, 0x2f63b0], [0.42, 0x2ec4b6], [0.62, 0xe9d758], [0.8, 0xff8a2a], [1, 0xe5322b]]
  .map(([t, c]) => [t, new THREE.Color(c)]);
function colormap(t, out) {
  t = Math.min(1, Math.max(0, t));
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, c0] = STOPS[i - 1], [t1, c1] = STOPS[i];
      return out.copy(c0).lerp(c1, (t - t0) / (t1 - t0));
    }
  }
  return out.copy(STOPS[STOPS.length - 1][1]);
}

// ---------------------------------------------------------------------------
// Fluid engine: collocated stable-fluids on a cubic grid inside the capsule.
// All constants below are VISUALIZATION parameters (see "Model assumptions").
// ---------------------------------------------------------------------------
const MODEL = {
  h: 0.14,            // grid spacing, m
  jacobi: 16,         // pressure iterations
  kappa: 0.002,       // scalar (mixing) diffusivity, m²/s
  beta: 0.35,         // buoyancy gain per unit relative temperature
  cool: 0.08,         // relative temperature loss rate, 1/s
  drag: 0.25,         // velocity damping, 1/s
  vmax: 1.4,          // velocity clamp, m/s
  srcT: 1.6, srcS: 1.0, srcX: 0.9,  // source rates per unit intensity, 1/s
  extinguish: 0.42,   // relative intensity below which the model flame goes out
};

class Domain {
  constructor(bounds, radiusAt) {
    const h = MODEL.h;
    this.h = h;
    this.min = bounds.min.clone();
    const size = new THREE.Vector3().subVectors(bounds.max, bounds.min);
    this.nx = Math.max(6, Math.round(size.x / h)); this.ny = Math.max(6, Math.round(size.y / h)); this.nz = Math.max(6, Math.round(size.z / h));
    this.n = this.nx * this.ny * this.nz;
    this.offs = [1, -1, this.nx, -this.nx, this.nx * this.ny, -this.nx * this.ny];
    this.cx = (bounds.min.x + bounds.max.x) / 2; this.cz = (bounds.min.z + bounds.max.z) / 2;
    this.solid = new Uint8Array(this.n);
    let fluid = 0;
    for (let k = 0; k < this.nz; k++) for (let j = 0; j < this.ny; j++) for (let i = 0; i < this.nx; i++) {
      const p = this.center(i, j, k);
      const r = Math.hypot(p.x - this.cx, p.z - this.cz);
      const inside = r < radiusAt(p.y) * 0.93 - h * 0.35 && j > 0 && j < this.ny - 1 && i > 0 && i < this.nx - 1 && k > 0 && k < this.nz - 1;
      this.solid[this.idx(i, j, k)] = inside ? 0 : 1;
      if (inside) fluid++;
    }
    this.fluidCount = fluid;
  }
  idx(i, j, k) { return i + this.nx * (j + this.ny * k); }
  center(i, j, k) { return new THREE.Vector3(this.min.x + (i + 0.5) * this.h, this.min.y + (j + 0.5) * this.h, this.min.z + (k + 0.5) * this.h); }
  cellOf(p) {
    return [Math.floor((p.x - this.min.x) / this.h), Math.floor((p.y - this.min.y) / this.h), Math.floor((p.z - this.min.z) / this.h)];
  }
  inFluid(p) {
    const [i, j, k] = this.cellOf(p);
    if (i < 0 || j < 0 || k < 0 || i >= this.nx || j >= this.ny || k >= this.nz) return false;
    return this.solid[this.idx(i, j, k)] === 0;
  }
  // nearest fluid cell walking from p toward the capsule axis (for surface heat map)
  fluidCellNear(p) {
    const q = p.clone();
    const dir = new THREE.Vector3(this.cx - p.x, 0, this.cz - p.z);
    const len = dir.length() || 1; dir.multiplyScalar(this.h * 0.5 / len);
    for (let s = 0; s < 14; s++) {
      const [i, j, k] = this.cellOf(q);
      if (i >= 0 && j >= 0 && k >= 0 && i < this.nx && j < this.ny && k < this.nz && !this.solid[this.idx(i, j, k)]) return this.idx(i, j, k);
      q.add(dir);
    }
    return -1;
  }
  // a fluid cell close to a target point (used for vents and sources)
  snap(p) {
    let best = -1, bd = 1e9;
    for (let k = 0; k < this.nz; k++) for (let j = 0; j < this.ny; j++) for (let i = 0; i < this.nx; i++) {
      const id = this.idx(i, j, k); if (this.solid[id]) continue;
      const c = this.center(i, j, k); const d = c.distanceToSquared(p);
      if (d < bd) { bd = d; best = id; }
    }
    return best;
  }
  ijk(id) { const i = id % this.nx, j = Math.floor(id / this.nx) % this.ny, k = Math.floor(id / (this.nx * this.ny)); return [i, j, k]; }
}

// Forced ventilation as steady potential flow: ∇²φ = q (source at inlet, sink at outlet),
// Neumann walls; u = ∇φ normalised to unit mean speed at the inlet. Solved once per domain.
function ventField(d, inlet, outlet) {
  if (d._vent) return d._vent;
  const n = d.n, phi = new Float32Array(n), q = new Float32Array(n), nx = d.nx, nxy = d.nx * d.ny, h = d.h;
  for (const id of inlet) q[id] = 1 / inlet.length;
  for (const id of outlet) q[id] = -1 / outlet.length;
  for (let it = 0; it < 900; it++) {
    for (let k = 1; k < d.nz - 1; k++) for (let j = 1; j < d.ny - 1; j++) for (let i = 1; i < d.nx - 1; i++) {
      const id = i + nx * j + nxy * k; if (d.solid[id]) continue;
      let s = 0;
      for (let o = 0; o < 6; o++) { const nb = id + d.offs[o]; s += d.solid[nb] ? phi[id] : phi[nb]; }
      phi[id] = phi[id] * 0.25 + 0.75 * ((s - q[id]) / 6);
    }
  }
  const u = new Float32Array(n), v = new Float32Array(n), w = new Float32Array(n), ih = 1 / (2 * h);
  for (let k = 1; k < d.nz - 1; k++) for (let j = 1; j < d.ny - 1; j++) for (let i = 1; i < d.nx - 1; i++) {
    const id = i + nx * j + nxy * k; if (d.solid[id]) continue;
    const pc = phi[id], P = (o) => (d.solid[o] ? pc : phi[o]);
    // q>0 makes φ a local minimum at the inlet, so u = +∇φ points away from it (toward the outlet)
    u[id] = (P(id + 1) - P(id - 1)) * ih; v[id] = (P(id + nx) - P(id - nx)) * ih; w[id] = (P(id + nxy) - P(id - nxy)) * ih;
  }
  let m = 0; for (const id of inlet) m += Math.hypot(u[id], v[id], w[id]);
  m = m / Math.max(1, inlet.length) || 1;
  for (let id = 0; id < n; id++) { u[id] /= m; v[id] /= m; w[id] /= m; }
  d._vent = { u, v, w };
  return d._vent;
}

class FluidSim {
  constructor(domain, anchors) {
    this.d = domain; const n = domain.n;
    this.u = new Float32Array(n); this.v = new Float32Array(n); this.w = new Float32Array(n);
    this.u0 = new Float32Array(n); this.v0 = new Float32Array(n); this.w0 = new Float32Array(n);
    this.T = new Float32Array(n); this.S = new Float32Array(n); this.X = new Float32Array(n);
    this.tmp = new Float32Array(n); this.p = new Float32Array(n); this.div = new Float32Array(n);
    this.ut = new Float32Array(n); this.vt = new Float32Array(n); this.wt = new Float32Array(n);
    this.anchors = anchors;
    this.params = { g: 0, o2: 21, kpa: 101.3, flow: 20 };
    this.fire = { on: false, pos: "seat", intensity: 0, out: false, cell: -1 };
    this.time = 0;
    this.buildVents();
  }
  buildVents() {
    const d = this.d;
    const pick = (p, r) => {
      const c0 = d.snap(p); const out = [];
      if (c0 < 0) return out;
      const [i0, j0, k0] = d.ijk(c0);
      for (let dk = -r; dk <= r; dk++) for (let dj = -r; dj <= r; dj++) {
        const i = i0, j = j0 + dj, k = k0 + dk;
        if (j < 0 || k < 0 || j >= d.ny || k >= d.nz) continue;
        const id = d.idx(i, j, k); if (!d.solid[id]) out.push(id);
      }
      return out;
    };
    this.inlet = pick(this.anchors.inlet, 1);
    this.outlet = pick(this.anchors.outlet, 1);
    this.inletDir = new THREE.Vector3().subVectors(this.anchors.center, this.anchors.inlet).setY(0).normalize();
    this.vent = ventField(d, this.inlet, this.outlet);
  }
  reset() {
    for (const a of [this.u, this.v, this.w, this.T, this.S, this.X, this.p]) a.fill(0);
    this.total();
    this.time = 0; this.fire.intensity = 0; this.fire.out = false;
  }
  ignite(pos) {
    this.fire.on = true; this.fire.out = false; this.fire.pos = pos;
    this.fire.cell = this.d.snap(this.anchors.fire[pos]);
    this.fire.intensity = 1;
  }
  extinguish() { this.fire.on = false; this.fire.intensity = 0; }

  sample(f, x, y, z) {
    const d = this.d, h = d.h;
    let fx = (x - d.min.x) / h - 0.5, fy = (y - d.min.y) / h - 0.5, fz = (z - d.min.z) / h - 0.5;
    fx = Math.min(Math.max(fx, 0), d.nx - 1.001); fy = Math.min(Math.max(fy, 0), d.ny - 1.001); fz = Math.min(Math.max(fz, 0), d.nz - 1.001);
    const i = fx | 0, j = fy | 0, k = fz | 0, a = fx - i, b = fy - j, c = fz - k;
    const nx = d.nx, nxy = d.nx * d.ny, o = i + nx * j + nxy * k;
    const c00 = f[o] * (1 - a) + f[o + 1] * a, c10 = f[o + nx] * (1 - a) + f[o + nx + 1] * a;
    const c01 = f[o + nxy] * (1 - a) + f[o + nxy + 1] * a, c11 = f[o + nxy + nx] * (1 - a) + f[o + nxy + nx + 1] * a;
    return (c00 * (1 - b) + c10 * b) * (1 - c) + (c01 * (1 - b) + c11 * b) * c;
  }
  advect(dst, src, dt) {
    const d = this.d, h = d.h;
    for (let k = 1; k < d.nz - 1; k++) for (let j = 1; j < d.ny - 1; j++) for (let i = 1; i < d.nx - 1; i++) {
      const id = d.idx(i, j, k);
      if (d.solid[id]) { dst[id] = 0; continue; }
      const x = d.min.x + (i + 0.5) * h - dt * this.u0[id];
      const y = d.min.y + (j + 0.5) * h - dt * this.v0[id];
      const z = d.min.z + (k + 0.5) * h - dt * this.w0[id];
      dst[id] = this.sample(src, x, y, z);
    }
  }
  diffuse(f, dt) {
    const d = this.d, a = MODEL.kappa * dt / (d.h * d.h), nx = d.nx, nxy = d.nx * d.ny, t = this.tmp;
    t.set(f);
    for (let k = 1; k < d.nz - 1; k++) for (let j = 1; j < d.ny - 1; j++) for (let i = 1; i < d.nx - 1; i++) {
      const id = i + nx * j + nxy * k; if (d.solid[id]) continue;
      let s = 0, c = 0;
      for (let q = 0; q < 6; q++) { const o = id + d.offs[q]; if (!d.solid[o]) { s += t[o]; c++; } }
      f[id] = t[id] + a * (s - c * t[id]);
    }
  }
  project() {
    const d = this.d, h = d.h, nx = d.nx, nxy = d.nx * d.ny, u = this.u, v = this.v, w = this.w, p = this.p, div = this.div;
    if (!this.isOut) { this.isOut = new Uint8Array(d.n); for (const id of this.outlet) this.isOut[id] = 1; }
    const isOut = this.isOut, sol = d.solid, ih = 1 / (2 * h);
    for (let k = 1; k < d.nz - 1; k++) for (let j = 1; j < d.ny - 1; j++) for (let i = 1; i < d.nx - 1; i++) {
      const id = i + nx * j + nxy * k; if (sol[id]) { div[id] = 0; continue; }
      const ue = sol[id + 1] ? 0 : u[id + 1], uw = sol[id - 1] ? 0 : u[id - 1];
      const vn = sol[id + nx] ? 0 : v[id + nx], vs = sol[id - nx] ? 0 : v[id - nx];
      const wf = sol[id + nxy] ? 0 : w[id + nxy], wb = sol[id - nxy] ? 0 : w[id - nxy];
      div[id] = (ue - uw + vn - vs + wf - wb) * ih;
    }
    for (let it = 0; it < MODEL.jacobi; it++) {
      for (let k = 1; k < d.nz - 1; k++) for (let j = 1; j < d.ny - 1; j++) for (let i = 1; i < d.nx - 1; i++) {
        const id = i + nx * j + nxy * k; if (d.solid[id]) continue;
        if (isOut[id]) { p[id] = 0; continue; }
        let s = 0;
        for (let q = 0; q < 6; q++) { const o = id + d.offs[q]; s += sol[o] ? p[id] : p[o]; }
        p[id] = (s - div[id] * h * h) / 6;
      }
    }
    for (let k = 1; k < d.nz - 1; k++) for (let j = 1; j < d.ny - 1; j++) for (let i = 1; i < d.nx - 1; i++) {
      const id = i + nx * j + nxy * k; if (sol[id]) { u[id] = v[id] = w[id] = 0; continue; }
      const pc = p[id];
      u[id] -= ((sol[id + 1] ? pc : p[id + 1]) - (sol[id - 1] ? pc : p[id - 1])) * ih;
      v[id] -= ((sol[id + nx] ? pc : p[id + nx]) - (sol[id - nx] ? pc : p[id - nx])) * ih;
      w[id] -= ((sol[id + nxy] ? pc : p[id + nxy]) - (sol[id - nxy] ? pc : p[id - nxy])) * ih;
    }
  }
  setInlet() {
    // fresh supply air at the inlet
    for (const id of this.inlet) { this.S[id] = 0; this.X[id] = 0; this.T[id] = 0; }
  }
  total() {
    // forced ventilation (potential flow, scaled to the inlet speed) + buoyant dynamic part
    const s = this.params.flow / 100, V = this.vent;
    for (let id = 0; id < this.d.n; id++) {
      this.ut[id] = this.u[id] + s * V.u[id]; this.vt[id] = this.v[id] + s * V.v[id]; this.wt[id] = this.w[id] + s * V.w[id];
    }
  }
  step(dt) {
    const d = this.d, P = this.params, F = this.fire;
    // 1) burning intensity from local ppO2 (conceptual scaling) and sources
    if (F.on && F.cell >= 0) {
      const [ci, cj, ck] = d.ijk(F.cell); let xs = 0, xn = 0;
      for (let dk = -1; dk <= 1; dk++) for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        const id = d.idx(ci + di, cj + dj, ck + dk); if (!d.solid[id]) { xs += this.X[id]; xn++; }
      }
      const ppo2 = P.kpa * (P.o2 / 100) * (1 - xs / Math.max(1, xn));
      const target = Math.min(2.2, ppo2 / 21.3);
      F.intensity += (target - F.intensity) * Math.min(1, dt * 0.6);
      if (F.intensity < MODEL.extinguish) { F.on = false; F.out = true; F.intensity = 0; }
      const I = F.intensity, [i0, j0, k0] = d.ijk(F.cell);
      for (let dk = -1; dk <= 1; dk++) for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
        const id = d.idx(i0 + di, j0 + dj, k0 + dk); if (d.solid[id]) continue;
        const wgt = di === 0 && dj === 0 && dk === 0 ? 1 : 0.18;
        this.T[id] += MODEL.srcT * I * dt * wgt;
        this.S[id] += MODEL.srcS * I * dt * wgt;
        this.X[id] = Math.min(0.95, this.X[id] + MODEL.srcX * I * dt * wgt);
      }
    }
    // 2) body forces: buoyancy only where gravity exists (0 g → none)
    const ay = 9.81 * P.g * MODEL.beta, damp = 1 - MODEL.drag * dt;
    for (let id = 0; id < d.n; id++) {
      if (d.solid[id]) continue;
      this.v[id] += dt * ay * this.T[id];
      this.u[id] *= damp; this.v[id] *= damp; this.w[id] *= damp;
      const sp = Math.hypot(this.u[id], this.v[id], this.w[id]);
      if (sp > MODEL.vmax) { const f = MODEL.vmax / sp; this.u[id] *= f; this.v[id] *= f; this.w[id] *= f; }
    }
    // 3) dynamic (buoyancy-driven) velocity, advected by the TOTAL flow
    this.total();
    this.u0.set(this.ut); this.v0.set(this.vt); this.w0.set(this.wt);
    this.tmp.set(this.u); this.advect(this.u, this.tmp, dt);
    this.tmp.set(this.v); this.advect(this.v, this.tmp, dt);
    this.tmp.set(this.w); this.advect(this.w, this.tmp, dt);
    // 4) incompressibility of the dynamic part
    this.project();
    // 5) scalars: advect by total flow (forced ventilation + buoyant plume) + diffuse + relax
    this.total();
    this.u0.set(this.ut); this.v0.set(this.vt); this.w0.set(this.wt);
    for (const f of [this.T, this.S, this.X]) { this.tmp.set(f); this.advect(f, this.tmp, dt); this.diffuse(f, dt); }
    const cool = 1 - MODEL.cool * dt;
    for (let id = 0; id < d.n; id++) { this.T[id] *= cool; if (this.S[id] < 0) this.S[id] = 0; if (this.X[id] < 0) this.X[id] = 0; }
    for (const id of this.outlet) { this.S[id] *= 0.6; this.T[id] *= 0.6; }
    this.setInlet();
    this.time += dt;
  }
  velocityAt(p, out) { return out.set(this.sample(this.ut, p.x, p.y, p.z), this.sample(this.vt, p.x, p.y, p.z), this.sample(this.wt, p.x, p.y, p.z)); }
  metrics() {
    const d = this.d; let filled = 0, vmaxUp = 0;
    for (let id = 0; id < d.n; id++) { if (d.solid[id]) continue; if (this.S[id] > 0.05) filled++; if (Math.abs(this.vt[id]) > vmaxUp) vmaxUp = Math.abs(this.vt[id]); }
    return {
      smokePct: 100 * filled / d.fluidCount,
      o2Dep: this.fire.cell >= 0 ? 100 * this.X[this.fire.cell] : 0,
      rise: vmaxUp * 100,
      intensity: this.fire.intensity,
    };
  }
}

// ---------------------------------------------------------------------------
// Sprites / textures
// ---------------------------------------------------------------------------
function radialTexture(stops) {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d"), gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  for (const [o, col] of stops) gr.addColorStop(o, col);
  g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
const TEX = {};
function textures() {
  if (TEX.dot) return TEX;
  TEX.dot = radialTexture([[0, "rgba(255,255,255,1)"], [0.35, "rgba(255,255,255,.75)"], [1, "rgba(255,255,255,0)"]]);
  TEX.core = radialTexture([[0, "rgba(244,248,252,1)"], [0.3, "rgba(160,200,255,.95)"], [0.7, "rgba(40,90,255,.45)"], [1, "rgba(10,40,200,0)"]]);
  TEX.halo = radialTexture([[0, "rgba(40,100,255,.55)"], [0.5, "rgba(20,60,230,.22)"], [1, "rgba(10,30,160,0)"]]);
  TEX.soot = radialTexture([[0, "rgba(255,230,160,1)"], [0.35, "rgba(255,150,50,.85)"], [0.75, "rgba(230,70,20,.35)"], [1, "rgba(150,30,10,0)"]]);
  return TEX;
}

// ---------------------------------------------------------------------------
// One scenario = scene + capsule clone + fluid sim + particles + flame
// ---------------------------------------------------------------------------
class Scenario {
  constructor(app, key) {
    this.app = app; this.key = key;
    this.scene = new THREE.Scene();
    this.scene.add(new THREE.HemisphereLight(0xbcd6ee, 0x0a0c12, 0.9));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(4, 6, 5); this.scene.add(sun);
    const rim = new THREE.DirectionalLight(0x6fa3d8, 0.7); rim.position.set(-5, 2, -4); this.scene.add(rim);
    this.stars();
    this.capsule = app.makeCapsule();
    this.scene.add(this.capsule.group);
    this.sim = new FluidSim(app.domain, app.anchors);
    this.flameLight = new THREE.PointLight(0x5a8cff, 0, 3.2, 1.6); this.scene.add(this.flameLight);
    this.buildParticles(); this.buildFlame(); this.buildZones();
    this.habitat = "iss";
  }
  stars() {
    const n = 500, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(30 + Math.random() * 20);
      pos.set([v.x, v.y, v.z], i * 3);
    }
    const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.scene.add(new THREE.Points(g, new THREE.PointsMaterial({ color: 0x6b7a90, size: 0.09, sizeAttenuation: true })));
  }
  buildParticles() {
    const T = textures();
    const mk = (n, size, blending) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
      g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 4), 4));
      const m = new THREE.PointsMaterial({ size, map: T.dot, vertexColors: true, transparent: true, depthWrite: false, blending, sizeAttenuation: true });
      const pts = new THREE.Points(g, m); pts.frustumCulled = false; this.scene.add(pts);
      return { pts, n, age: new Float32Array(n).fill(1e9), life: new Float32Array(n), alive: new Uint8Array(n), next: 0 };
    };
    this.smoke = mk(2200, 0.16, THREE.NormalBlending);
    this.air = mk(650, 0.045, THREE.AdditiveBlending);
    this.airSeeded = false;
  }
  buildFlame() {
    const T = textures();
    this.flame = new THREE.Group();
    const spr = (map, blending) => new THREE.Sprite(new THREE.SpriteMaterial({ map, transparent: true, depthWrite: false, blending }));
    this.fHalo = spr(T.halo, THREE.AdditiveBlending); this.fCore = spr(T.core, THREE.AdditiveBlending); this.fSoot = spr(T.soot, THREE.AdditiveBlending);
    this.flame.add(this.fHalo, this.fSoot, this.fCore);
    this.flame.visible = false; this.scene.add(this.flame);
  }
  buildZones() {
    const a = this.app.anchors;
    this.zones = new THREE.Group(); this.scene.add(this.zones);
    const ring = (pos, color, key, r = 0.12) => {
      const m = new THREE.Mesh(new THREE.SphereGeometry(r, 20, 14), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.38, depthWrite: false }));
      m.position.copy(pos); m.userData.zone = key; this.zones.add(m);
      const halo = new THREE.Mesh(new THREE.RingGeometry(r * 1.4, r * 1.65, 40), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.8, side: THREE.DoubleSide, depthWrite: false }));
      halo.position.copy(pos); halo.userData.zone = key; halo.userData.billboard = true; this.zones.add(halo);
      return m;
    };
    ring(a.inlet, 0x6fa3d8, "vent");
    ring(a.outlet, 0xbcd6ee, "sensor");
    ring(a.atmo, 0x2ec4b6, "atmosphere", 0.1);
    this.fireMarker = ring(a.fire.seat, 0xff8a2a, "fire");
  }
  setFirePos(pos) {
    const p = this.app.anchors.fire[pos];
    this.zones.children.filter((c) => c.userData.zone === "fire").forEach((c) => c.position.copy(p));
  }
  applyHabitat(key, h) { this.habitat = key; Object.assign(this.sim.params, { g: h.g, o2: h.o2, kpa: h.kpa }); }

  emitSmoke(dt) {
    const S = this.smoke, F = this.sim.fire;
    if (!F.on) return;
    const rate = 260 * F.intensity * dt;
    const c = this.app.anchors.fire[F.pos], pos = S.pts.geometry.attributes.position.array;
    for (let e = 0; e < rate; e++) {
      const i = S.next; S.next = (S.next + 1) % S.n;
      const r = new THREE.Vector3().randomDirection().multiplyScalar(0.05 + Math.random() * 0.06);
      pos[i * 3] = c.x + r.x; pos[i * 3 + 1] = c.y + r.y; pos[i * 3 + 2] = c.z + r.z;
      S.age[i] = 0; S.life[i] = 18 + Math.random() * 16; S.alive[i] = 1;
    }
  }
  seedAir(i) {
    const A = this.air, pos = A.pts.geometry.attributes.position.array, a = this.app.anchors, d = this.app.domain;
    const fromInlet = Math.random() < 0.45;
    let p;
    if (fromInlet) p = a.inlet.clone().add(new THREE.Vector3((Math.random() - .5) * .3, (Math.random() - .5) * .35, (Math.random() - .5) * .35));
    else {
      for (let t = 0; t < 20; t++) {
        p = new THREE.Vector3(d.min.x + Math.random() * d.nx * d.h, d.min.y + Math.random() * d.ny * d.h, d.min.z + Math.random() * d.nz * d.h);
        if (d.inFluid(p)) break;
      }
    }
    pos[i * 3] = p.x; pos[i * 3 + 1] = p.y; pos[i * 3 + 2] = p.z;
    A.age[i] = 0; A.life[i] = 6 + Math.random() * 8; A.alive[i] = 1;
  }
  stepParticles(dt) {
    const sim = this.sim, d = this.app.domain, vel = new THREE.Vector3(), p = new THREE.Vector3();
    // smoke: advected + random-walk diffusion (no buoyant rise of its own: it rides the flow field)
    const S = this.smoke, sp = S.pts.geometry.attributes.position.array, sc = S.pts.geometry.attributes.color.array;
    const diffStep = Math.sqrt(2 * MODEL.kappa * dt) * 1.6;
    for (let i = 0; i < S.n; i++) {
      if (!S.alive[i]) { sc[i * 4 + 3] = 0; continue; }
      S.age[i] += dt;
      p.set(sp[i * 3], sp[i * 3 + 1], sp[i * 3 + 2]);
      sim.velocityAt(p, vel);
      p.addScaledVector(vel, dt);
      p.x += (Math.random() - .5) * 2 * diffStep; p.y += (Math.random() - .5) * 2 * diffStep; p.z += (Math.random() - .5) * 2 * diffStep;
      if (!d.inFluid(p) || S.age[i] > S.life[i]) { S.alive[i] = 0; sc[i * 4 + 3] = 0; continue; }
      sp[i * 3] = p.x; sp[i * 3 + 1] = p.y; sp[i * 3 + 2] = p.z;
      const t = S.age[i] / S.life[i], hot = Math.min(1, sim.sample(sim.T, p.x, p.y, p.z) * 0.8);
      sc[i * 4] = 0.55 + 0.35 * hot; sc[i * 4 + 1] = 0.56 + 0.12 * hot; sc[i * 4 + 2] = 0.6 - 0.2 * hot;
      sc[i * 4 + 3] = 0.42 * Math.min(1, S.age[i] * 2) * (1 - t);
    }
    S.pts.geometry.attributes.position.needsUpdate = true; S.pts.geometry.attributes.color.needsUpdate = true;
    // air tracers
    const A = this.air, ap = A.pts.geometry.attributes.position.array, ac = A.pts.geometry.attributes.color.array;
    if (!this.airSeeded) { for (let i = 0; i < A.n; i++) { this.seedAir(i); A.age[i] = Math.random() * A.life[i]; } this.airSeeded = true; }
    for (let i = 0; i < A.n; i++) {
      A.age[i] += dt;
      p.set(ap[i * 3], ap[i * 3 + 1], ap[i * 3 + 2]);
      sim.velocityAt(p, vel);
      p.addScaledVector(vel, dt);
      if (!d.inFluid(p) || A.age[i] > A.life[i]) { this.seedAir(i); continue; }
      ap[i * 3] = p.x; ap[i * 3 + 1] = p.y; ap[i * 3 + 2] = p.z;
      const s = Math.min(1, vel.length() / 0.3);
      ac[i * 4] = 0.35 + 0.3 * s; ac[i * 4 + 1] = 0.65 + 0.25 * s; ac[i * 4 + 2] = 1; ac[i * 4 + 3] = (0.15 + 0.6 * s) * Math.min(1, A.age[i]) * Math.min(1, (A.life[i] - A.age[i]));
    }
    A.pts.geometry.attributes.position.needsUpdate = true; A.pts.geometry.attributes.color.needsUpdate = true;
  }
  updateFlame(t) {
    const F = this.sim.fire, P = this.sim.params;
    this.flame.visible = F.on;
    this.flameLight.intensity = F.on ? 2.2 * F.intensity : 0;
    if (!F.on) return;
    const c = this.app.anchors.fire[F.pos], I = Math.max(0.2, F.intensity);
    const flick = REDUCED ? 1 : 1 + 0.06 * Math.sin(t * 13) + 0.04 * Math.sin(t * 29 + 1.3);
    const base = 0.32 * Math.sqrt(I) * flick;
    // CONCEPTUAL shape: sphere in 0 g, teardrop elongated with √g; leaned downstream by ventilation
    const elong = 1 + 1.7 * Math.sqrt(P.g);
    const lean = new THREE.Vector3().copy(this.sim.inletDir).multiplyScalar(0.18 * Math.min(1, P.flow / 30));
    this.flame.position.copy(c).add(lean).add(new THREE.Vector3(0, base * (elong - 1) * 0.45, 0));
    this.fCore.scale.set(base, base * elong, 1);
    this.fHalo.scale.set(base * 2.6, base * 2.6 * (0.6 + 0.4 * elong), 1);
    const sootiness = Math.min(1, P.g * 1.6);
    this.fSoot.scale.set(base * 1.1, base * elong * 1.35, 1);
    this.fSoot.material.opacity = sootiness; this.fSoot.position.y = base * 0.25 * elong;
    this.fCore.material.opacity = 0.95; this.fHalo.material.opacity = 0.75 * (1 - 0.6 * sootiness);
    this.flameLight.position.copy(this.flame.position);
    this.flameLight.color.setHSL(0.62 - 0.55 * sootiness, 0.9, 0.6);
  }
  updateHeat(mode) {
    const cap = this.capsule, sim = this.sim;
    if (!cap.hullColors) return;
    const col = cap.hullColors.array, map = cap.vertexCell, tmp = new THREE.Color();
    const f = mode === "o2" ? sim.X : mode === "temp" ? sim.T : sim.S;
    const gain = mode === "o2" ? 3.2 : mode === "temp" ? 1.4 : 2.2;
    for (let v = 0; v < map.length; v++) {
      const id = map[v];
      const val = id >= 0 ? f[id] * gain : 0;
      colormap(val, tmp);
      col[v * 3] = tmp.r; col[v * 3 + 1] = tmp.g; col[v * 3 + 2] = tmp.b;
    }
    cap.hullColors.needsUpdate = true;
  }
  billboard(camera) { this.zones.children.forEach((c) => { if (c.userData.billboard) c.quaternion.copy(camera.quaternion); }); }
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
class App {
  constructor(model) {
    this.wrap = $("s3-canvas-wrap");
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping; this.renderer.toneMappingExposure = 1.05;
    this.renderer.localClippingEnabled = true;
    this.renderer.setScissorTest(true);
    this.wrap.appendChild(this.renderer.domElement);

    this.model = model;
    this.prepareGeometry();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.05, 200);
    const c = this.center, R = this.radius;
    this.camera.position.set(c.x + R * 1.45, c.y + R * 0.5, c.z + R * 1.8);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.copy(c); this.controls.enableDamping = true; this.controls.dampingFactor = 0.08;
    this.controls.minDistance = R * 0.6; this.controls.maxDistance = R * 7;
    this.controls.screenSpacePanning = true;

    this.clipPlane = new THREE.Plane(new THREE.Vector3(0, 0, -1), c.z);
    this.state = { playing: true, speed: 1, heat: "smoke", opacity: 1, cut: true, air: true, smoke: true, zones: true, split: false, firePos: "seat", habA: "iss", habB: "mars" };
    this.A = new Scenario(this, "A");
    this.B = null;
    this.raycaster = new THREE.Raycaster(); this.pointer = new THREE.Vector2();
    this.clock = new THREE.Clock(); this.acc = 0; this.frame = 0;
    this.resize();
    new ResizeObserver(() => this.resize()).observe(this.wrap);
    this.renderer.domElement.addEventListener("pointerdown", (e) => { this.down = [e.clientX, e.clientY]; });
    this.renderer.domElement.addEventListener("pointerup", (e) => this.onClick(e));
    this.loop = this.loop.bind(this); requestAnimationFrame(this.loop);
  }

  prepareGeometry() {
    // Collect hull + window geometries in world space; build capsule profile & fluid domain.
    const hull = [], glass = [];
    this.model.updateMatrixWorld(true);
    this.model.traverse((o) => {
      if (!o.isMesh) return;
      const g = o.geometry.clone(); g.applyMatrix4(o.matrixWorld);
      const col = o.material && o.material.color ? o.material.color : new THREE.Color(0xcccccc);
      (col.b > col.r + 0.25 ? glass : hull).push(g);
    });
    this.hullGeos = hull; this.glassGeos = glass;
    const box = new THREE.Box3();
    [...hull, ...glass].forEach((g) => { g.computeBoundingBox(); box.union(g.boundingBox); });
    this.box = box; this.center = box.getCenter(new THREE.Vector3()); this.radius = box.getSize(new THREE.Vector3()).length() / 2;
    // radius profile from geometry (both primitives), smoothed with a running max
    const BINS = 40, prof = new Float32Array(BINS), ymin = box.min.y, ymax = box.max.y;
    const cx = this.center.x, cz = this.center.z;
    for (const g of [...hull, ...glass]) {
      const p = g.attributes.position;
      for (let i = 0; i < p.count; i++) {
        const y = p.getY(i), k = Math.min(BINS - 1, Math.floor((y - ymin) / (ymax - ymin) * BINS));
        prof[k] = Math.max(prof[k], Math.hypot(p.getX(i) - cx, p.getZ(i) - cz));
      }
    }
    const sm = prof.map((_, k) => Math.max(prof[Math.max(0, k - 1)], prof[k], prof[Math.min(BINS - 1, k + 1)]));
    this.radiusAt = (y) => {
      const t = (y - ymin) / (ymax - ymin) * BINS - 0.5, k = Math.max(0, Math.min(BINS - 1, Math.floor(t))), k2 = Math.min(BINS - 1, k + 1), a = Math.max(0, Math.min(1, t - k));
      return sm[k] * (1 - a) + sm[k2] * a;
    };
    this.domain = new Domain(box, this.radiusAt);
    const H = ymax - ymin, at = (fy, fx, fz = 0) => new THREE.Vector3(cx + fx * this.radiusAt(ymin + fy * H), ymin + fy * H, cz + fz);
    this.anchors = {
      center: new THREE.Vector3(cx, ymin + 0.45 * H, cz),
      inlet: at(0.62, 0.72, -0.1), outlet: at(0.16, -0.72, -0.1),
      atmo: at(0.5, -0.15, -0.25),
      fire: { seat: at(0.2, 0.42, -0.25), center: at(0.42, 0.0, -0.1), vent: at(0.56, 0.5, -0.15) },
    };
  }

  makeCapsule() {
    const group = new THREE.Group();
    const hullMat = new THREE.MeshStandardMaterial({ color: 0xcfd2d7, metalness: 0.55, roughness: 0.38, side: THREE.DoubleSide, clippingPlanes: [this.clipPlane || new THREE.Plane()] });
    const glassMat = new THREE.MeshPhysicalMaterial({ color: 0x4fdbf1, metalness: 0.1, roughness: 0.12, transmission: 0.35, transparent: true, opacity: 0.85, side: THREE.DoubleSide, clippingPlanes: hullMat.clippingPlanes });
    const meshes = [];
    let hullColors = null, vertexCell = null;
    this.hullGeos.forEach((g0, idx) => {
      const g = g0.clone();
      if (idx === 0) {
        const n = g.attributes.position.count;
        hullColors = new THREE.BufferAttribute(new Float32Array(n * 3).fill(0.8), 3);
        g.setAttribute("color", hullColors);
        if (!this.vertexCellCache) {
          const cells = new Int32Array(n), p = new THREE.Vector3();
          for (let i = 0; i < n; i++) { p.fromBufferAttribute(g.attributes.position, i); cells[i] = this.domain.fluidCellNear(p); }
          this.vertexCellCache = cells;
        }
        vertexCell = this.vertexCellCache;
      } else {
        g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(g.attributes.position.count * 3).fill(1), 3));
      }
      const m = new THREE.Mesh(g, hullMat); meshes.push(m); group.add(m);
    });
    this.glassGeos.forEach((g) => group.add(new THREE.Mesh(g, glassMat)));
    return { group, hullMat, glassMat, meshes, hullColors, vertexCell };
  }

  applyLayers() {
    const s = this.state;
    for (const sc of this.scenarios()) {
      const cap = sc.capsule;
      cap.hullMat.vertexColors = s.heat !== "off"; cap.hullMat.color.set(s.heat !== "off" ? 0xffffff : 0xcfd2d7);
      cap.hullMat.metalness = s.heat !== "off" ? 0.15 : 0.55;
      cap.hullMat.transparent = s.opacity < 0.999; cap.hullMat.opacity = s.opacity; cap.hullMat.depthWrite = s.opacity > 0.6;
      cap.glassMat.opacity = Math.min(0.85, s.opacity * 0.85);
      const planes = s.cut ? [this.clipPlane] : [];
      cap.hullMat.clippingPlanes = planes; cap.glassMat.clippingPlanes = planes;
      cap.hullMat.needsUpdate = true; cap.glassMat.needsUpdate = true;
      sc.air.pts.visible = s.air; sc.smoke.pts.visible = s.smoke; sc.zones.visible = s.zones;
      if (s.heat === "off" && cap.hullColors) { cap.hullColors.array.fill(1); cap.hullColors.needsUpdate = true; }
    }
    $("s3-legend").hidden = s.heat === "off";
    $("s3-legend-title").textContent = { smoke: "Relative smoke concentration (model)", o2: "Relative O₂ depletion (model)", temp: "Relative gas temperature (model)" }[s.heat] || "";
  }
  scenarios() { return this.B ? [this.A, this.B] : [this.A]; }

  setSplit(on) {
    this.state.split = on;
    root.classList.toggle("split", on);
    if (on && !this.B) { this.B = new Scenario(this, "B"); this.B.applyHabitat(this.state.habB, DATA.habitats[this.state.habB]); this.B.sim.params.flow = this.A.sim.params.flow; this.B.setFirePos(this.state.firePos); if (this.A.sim.fire.on || this.A.sim.fire.out) this.B.sim.ignite(this.state.firePos); }
    $("s3-label-b").hidden = !on; $("s3-read-b").hidden = !on;
    this.applyLayers(); this.resize();
  }

  resize() {
    const w = this.wrap.clientWidth, h = this.wrap.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = (this.state && this.state.split ? w / 2 : w) / h; this.camera.updateProjectionMatrix();
  }

  onClick(e) {
    if (!this.down || Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]) > 5) return;
    const r = this.renderer.domElement.getBoundingClientRect();
    const split = this.state.split, half = r.width / 2;
    const inB = split && e.clientX - r.left > half;
    const vx = split ? (inB ? (e.clientX - r.left - half) / half : (e.clientX - r.left) / half) : (e.clientX - r.left) / r.width;
    this.pointer.set(vx * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const sc = inB ? this.B : this.A;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const targets = [];
    if (sc.zones.visible) targets.push(...sc.zones.children);
    if (sc.flame.visible) targets.push(sc.fCore);
    targets.push(...sc.capsule.group.children);
    // Raycasting ignores clipping planes: drop hits on the cut-away half, and let a
    // see-through hull (opacity < 0.5) never block the markers behind it.
    const hits = this.raycaster.intersectObjects(targets, false).filter((h) => {
      const isZone = !!h.object.userData.zone || h.object === sc.fCore;
      if (isZone) return true;
      if (this.state.cut && this.clipPlane.distanceToPoint(h.point) < 0) return false;
      if (this.state.opacity < 0.5) return false;
      return true;
    });
    const hit = hits[0];
    if (!hit) return;
    const zone = hit.object === sc.fCore ? "flame" : hit.object.userData.zone || "hull";
    UI.showEvidence(zone);
  }

  loop() {
    requestAnimationFrame(this.loop);
    const dtReal = Math.min(0.05, this.clock.getDelta());
    if (!this.wrap.offsetParent || document.hidden) return;   // section hidden: idle
    const s = this.state;
    if (s.playing) {
      this.acc += dtReal * s.speed;
      const step = 1 / 30; let n = 0;
      while (this.acc >= step && n < 4) {
        for (const sc of this.scenarios()) sc.sim.step(step);
        for (const sc of this.scenarios()) { sc.emitSmoke(step); sc.stepParticles(step); }
        this.acc -= step; n++;
      }
      if (n === 4) this.acc = 0;
    }
    const t = this.clock.elapsedTime;
    this.frame++;
    for (const sc of this.scenarios()) {
      sc.updateFlame(t);
      if (s.heat !== "off" && this.frame % 6 === 0) sc.updateHeat(s.heat);
      sc.billboard(this.camera);
    }
    this.controls.update();
    const w = this.wrap.clientWidth, h = this.wrap.clientHeight;
    if (s.split && this.B) {
      this.renderer.setViewport(0, 0, w / 2, h); this.renderer.setScissor(0, 0, w / 2, h); this.renderer.render(this.A.scene, this.camera);
      this.renderer.setViewport(w / 2, 0, w / 2, h); this.renderer.setScissor(w / 2, 0, w / 2, h); this.renderer.render(this.B.scene, this.camera);
    } else {
      this.renderer.setViewport(0, 0, w, h); this.renderer.setScissor(0, 0, w, h); this.renderer.render(this.A.scene, this.camera);
    }
    if (this.frame % 10 === 0) UI.readouts();
  }
}

// ---------------------------------------------------------------------------
// UI wiring
// ---------------------------------------------------------------------------
// Flammy (rule engine) reviews the simulated atmosphere: debounced while sliders move, forced on ignition.
let flammyTimer = null;
function notifyFlammy(force) {
  if (!window.flamaPostFlammy) return;
  clearTimeout(flammyTimer);
  flammyTimer = setTimeout(() => {
    const flow = +$("s3-flow").value;
    window.flamaPostFlammy({ type: "simulation", gravity: +$("s3-g").value, o2: +$("s3-o2").value,
      pressure_kpa: +$("s3-p").value, ventilation: flow > 0 ? "forced" : "none", flow_cm_s: flow }, { forceShow: !!force });
  }, force ? 0 : 700);
}

const esc = (t) => { const d = document.createElement("div"); d.textContent = t == null ? "" : String(t); return d.innerHTML; };
let app = null;
const UI = {
  hab: "iss",
  init() {
    const H = DATA.habitats, list = $("s3-habitats"), selB = $("s3-hab-b");
    list.innerHTML = Object.entries(H).map(([k, h]) =>
      `<button class="s3-hab" role="radio" aria-checked="false" data-hab="${k}" type="button"><b>${esc(h.name)}</b><span>${esc(h.sub)} · ${h.o2}% O₂ · ${h.kpa} kPa</span></button>`).join("");
    selB.innerHTML = Object.entries(H).filter(([k]) => k !== "custom").map(([k, h]) => `<option value="${k}">${esc(h.name)}</option>`).join("");
    selB.value = "mars";
    list.addEventListener("click", (e) => { const b = e.target.closest(".s3-hab"); if (b) this.setHabitat(b.dataset.hab); });
    const fl = DATA.flow; const fs = $("s3-flow"); fs.min = fl.min; fs.max = fl.max; fs.value = fl.default;
    for (const id of ["s3-g", "s3-o2", "s3-p"]) $(id).addEventListener("input", () => this.fromSliders());
    fs.addEventListener("input", () => this.fromSliders(true));
    document.querySelectorAll(".s3-prov").forEach((b) => b.addEventListener("click", () => this.showProvenance(b.dataset.prov)));
    $("s3-play").addEventListener("click", () => { if (!app) return; app.state.playing = !app.state.playing; $("s3-play").textContent = app.state.playing ? "Pause" : "Resume"; });
    $("s3-reset").addEventListener("click", () => { if (!app) return; for (const sc of app.scenarios()) { sc.sim.reset(); sc.sim.extinguish(); sc.smoke.alive.fill(0); } this.fireButton(); });
    document.querySelectorAll(".s3-seg-btn").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll(".s3-seg-btn").forEach((x) => x.classList.toggle("active", x === b)); if (app) app.state.speed = +b.dataset.speed;
    }));
    $("s3-fire-pos").addEventListener("change", (e) => { if (!app) return; app.state.firePos = e.target.value; for (const sc of app.scenarios()) { sc.setFirePos(e.target.value); if (sc.sim.fire.on) sc.sim.ignite(e.target.value); } });
    $("s3-ignite").addEventListener("click", () => {
      if (!app) return;
      const lit = app.A.sim.fire.on;
      for (const sc of app.scenarios()) lit ? sc.sim.extinguish() : sc.sim.ignite(app.state.firePos);
      this.fireButton();
      if (!lit) notifyFlammy(true);
      if (!lit && !this.toldFlammy && window.flammyBuddy) {
        this.toldFlammy = true;
        window.flammyBuddy.tip("Conceptual model", "With no gravity the smoke does not rise: it only goes where the vents push it. Click any zone to see the PSI data behind it.");
      }
    });
    $("s3-opacity").addEventListener("input", (e) => { $("s3-op-out").textContent = Math.round(e.target.value * 100) + "%"; if (app) { app.state.opacity = +e.target.value; app.applyLayers(); } });
    $("s3-op-out").textContent = "100%";
    for (const [id, key] of [["s3-cut", "cut"], ["s3-air", "air"], ["s3-smoke", "smoke"], ["s3-zones", "zones"]])
      $(id).addEventListener("change", (e) => { if (app) { app.state[key] = e.target.checked; app.applyLayers(); } });
    $("s3-heat").addEventListener("change", (e) => { if (app) { app.state.heat = e.target.value; app.applyLayers(); } });
    $("s3-compare").addEventListener("change", (e) => { if (app) app.setSplit(e.target.checked); this.labels(); });
    selB.addEventListener("change", (e) => { if (!app) return; app.state.habB = e.target.value; if (app.B) app.B.applyHabitat(e.target.value, H[e.target.value]); this.labels(); });
    $("s3-info-close").addEventListener("click", () => { $("s3-info").hidden = true; });
    $("s3-info").addEventListener("click", (e) => {
      const b = e.target.closest(".s3-lib[data-lib]");
      if (b) window.dispatchEvent(new CustomEvent("flama:abrir-archivo", { detail: { archivo: b.dataset.lib } }));
    });
    this.setHabitat("iss", true);
  },
  setHabitat(key, silent) {
    const h = DATA.habitats[key]; this.hab = key;
    document.querySelectorAll(".s3-hab").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.hab === key)));
    if (key !== "custom") { $("s3-g").value = h.g; $("s3-o2").value = h.o2; $("s3-p").value = h.kpa; }
    this.sync();
    if (app) { app.A.applyHabitat(key, { g: +$("s3-g").value, o2: +$("s3-o2").value, kpa: +$("s3-p").value }); }
    this.labels();
    if (!silent) notifyFlammy(false);
    if (!silent && window.flammyBuddy && h) window.flammyBuddy.tip(h.name, `${h.sub}. ${h.o2}% O₂ at ${h.kpa} kPa.` + (h.sources.o2.kind === "concept" ? " Atmosphere not in base_de_datos: shown as conceptual." : ""));
  },
  fromSliders(flowOnly) {
    if (!flowOnly && this.hab !== "custom") {
      this.hab = "custom";
      document.querySelectorAll(".s3-hab").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.hab === "custom")));
    }
    this.sync();
    if (app) {
      Object.assign(app.A.sim.params, { g: +$("s3-g").value, o2: +$("s3-o2").value, kpa: +$("s3-p").value, flow: +$("s3-flow").value });
      if (app.B) app.B.sim.params.flow = +$("s3-flow").value;
    }
    this.labels();
    notifyFlammy(false);
  },
  sync() {
    const g = +$("s3-g").value, o2 = +$("s3-o2").value, p = +$("s3-p").value, f = +$("s3-flow").value;
    $("s3-g-out").textContent = g.toFixed(2) + " g";
    $("s3-o2-out").textContent = o2.toFixed(1) + " %";
    $("s3-p-out").textContent = p.toFixed(1) + " kPa";
    $("s3-flow-out").textContent = f.toFixed(0) + " cm/s";
    $("s3-ppo2").textContent = (p * o2 / 100).toFixed(1) + " kPa";
    const src = DATA.habitats[this.hab].sources;
    const set = (key, s) => {
      const b = document.querySelector(`.s3-prov[data-prov="${key}"]`);
      b.textContent = s.kind === "psi" ? `Source: ${s.label}` : s.kind === "psi-file" ? "Source: base_de_datos (FM2 note)" : s.kind === "physics" ? "Physical constant" : "Conceptual · not in base_de_datos";
      b.classList.toggle("concept", s.kind === "concept");
    };
    set("g", src.g); set("o2", src.o2); set("kpa", src.kpa);
    window.dispatchEvent(new CustomEvent("flama:sim-atmosphere", { detail: { g, o2, kpa: p, flow: f } }));  // keeps bubble 1 ranking in sync
    const fb = document.querySelector('.s3-prov[data-prov="flow"]'); fb.textContent = "Source: PSI-25 / PSI-98 / PSI-100"; fb.classList.remove("concept");
  },
  labels() {
    const H = DATA.habitats, a = H[this.hab], g = +$("s3-g").value;
    $("s3-label-a").textContent = `A · ${a.name} · ${g.toFixed(2)} g`;
    if (app && app.B) { const b = H[app.state.habB]; $("s3-label-b").textContent = `B · ${b.name} · ${b.g.toFixed(2)} g`; }
  },
  fireButton() {
    const lit = app && app.A.sim.fire.on, btn = $("s3-ignite");
    btn.textContent = lit ? "Extinguish source" : "Ignite"; btn.classList.toggle("lit", !!lit);
  },
  readouts() {
    if (!app) return;
    $("s3-time").textContent = app.A.sim.time.toFixed(1);
    const card = (sc, label) => {
      const m = sc.sim.metrics(), F = sc.sim.fire;
      const state = F.on ? `${(m.intensity * 100).toFixed(0)}% intensity` : F.out ? "Out · O₂ starved (model)" : "Not ignited";
      return `<div class="s3-r-title">${esc(label)}</div>
        <div><span class="s3-r-k">Model flame</span><span class="s3-r-v ${F.out ? "warn" : ""}">${state}</span></div>
        <div><span class="s3-r-k">Smoke-filled volume</span><span class="s3-r-v">${m.smokePct.toFixed(1)}%</span></div>
        <div><span class="s3-r-k">O₂ depletion at source</span><span class="s3-r-v">${m.o2Dep.toFixed(1)}%</span></div>
        <div><span class="s3-r-k">Peak vertical flow</span><span class="s3-r-v">${m.rise.toFixed(1)} cm/s</span></div>`;
    };
    $("s3-read-a").innerHTML = card(app.A, $("s3-label-a").textContent + " · relative model values");
    if (app.B) $("s3-read-b").innerHTML = card(app.B, $("s3-label-b").textContent + " · relative model values");
    const F = app.A.sim.fire;
    $("s3-status").textContent = !app.state.playing ? "Paused" : F.out ? "Model flame out: local O₂ starved" : "";
    if (F.out) this.fireButton();
  },
  sourcesHTML(list) {
    if (!list || !list.length) return "";
    return `<div class="s3-src">${list.map((s) => this.srcHTML(s)).join("")}</div>`;
  },
  // Internal references only: record + exact table, opened in the app's database library.
  srcHTML(s) {
    const btn = (lib, label) => `<button type="button" class="s3-lib" data-lib="${esc(lib)}">${esc(label)}</button>`;
    const head = s.lib ? btn(s.lib, s.label + (s.doi ? " · DOI " + s.doi : "")) : `<span>${esc(s.label)}</span>`;
    const table = s.table_lib ? btn(s.table_lib, `Open the exact table: ${s.table_file}`) : "";
    return `<div>${head}${table}<small>${esc(s.detail || "")}</small></div>`;
  },
  showEvidence(zone) {
    const e = DATA.evidence[zone]; if (!e) return;
    const hasPsi = e.sources && e.sources.length;
    let html = `<span class="s3-tag ${hasPsi ? "psi" : "concept"}">${hasPsi ? "From base_de_datos" : "Conceptual"}</span><h4>${esc(e.title)}</h4><p>${esc(e.body)}</p>`;
    if (e.facts) html += `<dl>${e.facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>`;
    if (e.table) html += `<table><thead><tr>${e.table.cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead><tbody>${e.table.rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
    if (e.note) html += `<p class="s3-note">${esc(e.note)}</p>`;
    html += this.sourcesHTML(e.sources);
    $("s3-info-body").innerHTML = html; $("s3-info").hidden = false;
  },
  showProvenance(key) {
    let s, title;
    if (key === "flow") { title = "Ventilation range"; s = { kind: "psi", label: "PSI-25 · PSI-98 · PSI-100", detail: DATA.flow.source }; }
    else { s = DATA.habitats[this.hab].sources[key]; title = { g: "Gravity", o2: "Oxygen fraction", kpa: "Total pressure" }[key] + " · " + DATA.habitats[this.hab].name; }
    const tag = s.kind === "concept" ? `<span class="s3-tag concept">Conceptual</span>` : `<span class="s3-tag psi">${s.kind === "physics" ? "Physical constant" : "From base_de_datos"}</span>`;
    const link = `<div class="s3-src">${this.srcHTML(s)}</div>`;
    $("s3-info-body").innerHTML = `${tag}<h4>${esc(title)}</h4><p>${esc(s.detail || "")}</p>${link}`;
    $("s3-info").hidden = false;
  },
};

// ---------------------------------------------------------------------------
// Boot lazily: only when Section 02 is first shown
// ---------------------------------------------------------------------------
function fallbackModel() {
  const P = DATA.profile, pts = [];
  const n = P.radius.length;
  for (let k = 0; k < n; k++) pts.push(new THREE.Vector2(P.radius[k], P.ymin + (k + 0.5) / n * (P.ymax - P.ymin)));
  pts.push(new THREE.Vector2(0.01, P.ymax));
  const g = new THREE.LatheGeometry(pts, 64);
  const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0xcfd2d7 }));
  const grp = new THREE.Group(); grp.add(m); return grp;
}

let booted = false;
function boot() {
  if (booted) return; booted = true;
  const done = (model, note) => {
    $("s3-loading").remove();
    app = new App(model);
    window.__flamaSim3d = app;   // debug handle
    app.MODEL = MODEL;
    app.A.applyHabitat(UI.hab, { g: +$("s3-g").value, o2: +$("s3-o2").value, kpa: +$("s3-p").value });
    app.A.sim.params.flow = +$("s3-flow").value;
    app.applyLayers(); UI.labels(); UI.fireButton();
    if (note) $("s3-status").textContent = note;
    if (window.parent && window.frameElement) setTimeout(() => { const h = document.body.scrollHeight; if (h > 200) window.frameElement.style.height = (h + 20) + "px"; }, 60);
  };
  new GLTFLoader().load(DATA.glbUrl, (gltf) => done(gltf.scene), undefined,
    () => done(fallbackModel(), "CAD model unavailable: showing profile reconstruction"));
}

UI.init();
// Boot lazily: only once the Simulations bubble is actually opened (Three.js + CAD model load then).
const simView = document.getElementById("view-simulations");
const watched = [section, simView].filter(Boolean);
if (watched.length) {
  const check = () => { if (watched.every((el) => el.classList.contains("active"))) boot(); };
  watched.forEach((el) => new MutationObserver(check).observe(el, { attributes: true, attributeFilter: ["class"] }));
  check();
}
