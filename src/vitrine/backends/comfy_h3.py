# -*- coding: utf-8 -*-
"""MiniMax H3 Ref2VA on a local ComfyUI, driven over its HTTP API.

Ported from the standalone runner this pipeline used to shell out to. The
behaviour that mattered is kept exactly:

* it starts its own ComfyUI and stops only the process it started, and it
  refuses to attach to one already on the port -- an inherited server has log
  handles this code does not own, so a failure would be unattributable;
* peak VRAM is sampled from ``nvidia-smi`` rather than reported from inside the
  process, because the number people want is the card's, not the allocator's;
* ``ref_image_size`` stays ``"max"``. It was measured, not guessed: anything
  smaller loses the product's proportions between the wide and the detail take.

The workflow template is a ComfyUI *API-format* graph. Node ids are positional
in that file and are named here in one place, so a template change is one edit.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .base import BackendError, RenderResult, ShotSpec

# node ids inside the API-format template
N_REF0 = "100"        # LoadImage for the identity still
N_SAMPLER_IN = "19"   # prompt / size / length / ref_image_size
N_STEPS = "20"
N_SEED = "21"
N_FPS = "27"
N_SAVE = "28"

STARTUP_TIMEOUT_S = 600
RUN_TIMEOUT_S = 3600
POLL_S = 3.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _VramSampler(threading.Thread):
    """Samples nvidia-smi so peak VRAM is a measurement, not a guess."""

    def __init__(self, interval: float = 2.0):
        super().__init__(daemon=True)
        self.interval = interval
        self._stop = threading.Event()
        self.samples: list[int] = []

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10)
                if out.returncode == 0:
                    self.samples.append(int(out.stdout.strip().splitlines()[0]))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()

    def peak_since(self, mark: int) -> int | None:
        seg = self.samples[mark:]
        return max(seg) if seg else None


@dataclass
class ComfyH3Backend:
    """Renders shots on a local ComfyUI-H3 install."""

    comfy_root: Path
    workflow_template: Path
    logs_dir: Path
    host: str = "127.0.0.1"
    port: int = 8188
    lowvram: bool = True

    name: str = "comfy_h3"
    ref_slots: int = 3

    # ---- server lifecycle -------------------------------------------------
    @property
    def _base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _http(self, path: str, payload: dict | None = None, timeout: int = 30):
        url = f"{self._base}{path}"
        if payload is None:
            req = urllib.request.Request(url)
        else:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _ready(self) -> dict | None:
        try:
            return self._http("/system_stats", timeout=3)
        except Exception:
            return None

    def _start(self) -> subprocess.Popen:
        python = self.comfy_root / "python_embeded" / "python.exe"
        main = self.comfy_root / "ComfyUI" / "main.py"
        if not main.is_file():
            raise BackendError("server", f"no ComfyUI at {main}")
        exe = str(python) if python.is_file() else shutil.which("python") or "python"

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        op, ep = self.logs_dir / "comfy.stdout.log", self.logs_dir / "comfy.stderr.log"
        op.write_text("", encoding="utf-8")
        ep.write_text("", encoding="utf-8")
        args = [exe, "-s", str(main), "--listen", self.host, "--port", str(self.port)]
        if self.lowvram:
            args.append("--lowvram")
        proc = subprocess.Popen(
            args, cwd=str(self.comfy_root),
            stdout=open(op, "a", encoding="utf-8", buffering=1),
            stderr=open(ep, "a", encoding="utf-8", buffering=1))
        print(f"[{_now()}] started ComfyUI pid={proc.pid}", flush=True)

        deadline = time.time() + STARTUP_TIMEOUT_S
        while time.time() < deadline:
            if proc.poll() is not None:
                raise BackendError(
                    "server", f"ComfyUI exited during startup (code "
                              f"{proc.returncode}); see {ep}")
            if self._ready():
                print(f"[{_now()}] server ready", flush=True)
                return proc
            time.sleep(2)
        proc.terminate()
        raise BackendError("server", f"ComfyUI not ready in {STARTUP_TIMEOUT_S}s")

    # ---- graph ------------------------------------------------------------
    def stage_refs(self, episode: str, refs: Sequence[Path]) -> list[str]:
        """Copy references into ComfyUI's input tree and return its own paths."""
        dst_dir = self.comfy_root / "ComfyUI" / "input" / episode
        dst_dir.mkdir(parents=True, exist_ok=True)
        out = []
        for src in refs:
            if not Path(src).is_file():
                raise BackendError("refs", f"reference image is missing: {src}")
            shutil.copy2(src, dst_dir / Path(src).name)
            out.append(f"{episode}/{Path(src).name}")
        return out

    def build_graph(self, episode: str, shot: ShotSpec, staged: list[str]) -> dict:
        wf = json.loads(self.workflow_template.read_text(encoding="utf-8"))
        wf[N_REF0]["inputs"]["image"] = staged[0]
        for j, rel in enumerate(staged[1:], start=1):
            nid = str(int(N_REF0) + j)
            wf[nid] = {"class_type": "LoadImage", "inputs": {"image": rel}}
            wf[N_SAMPLER_IN]["inputs"][f"ref_images.ref_image_{j}"] = [nid, 0]
        wf[N_SAMPLER_IN]["inputs"].update({
            "prompt": shot.prompt, "width": shot.width, "height": shot.height,
            "length": shot.frames, "ref_image_size": "max"})
        wf[N_STEPS]["inputs"]["steps"] = shot.steps
        wf[N_SEED]["inputs"]["noise_seed"] = shot.seed
        wf[N_FPS]["inputs"]["fps"] = shot.fps
        wf[N_SAVE]["inputs"]["filename_prefix"] = f"{episode}/{shot.id}"
        return wf

    # ---- run --------------------------------------------------------------
    def _submit(self, wf: dict) -> str:
        res = self._http("/prompt", {"prompt": wf, "client_id": "vitrine"})
        if "prompt_id" not in res:
            raise BackendError("submit", json.dumps(res, ensure_ascii=False)[:1200])
        return res["prompt_id"]

    def _wait(self, prompt_id: str, proc: subprocess.Popen) -> dict:
        deadline = time.time() + RUN_TIMEOUT_S
        while time.time() < deadline:
            if proc.poll() is not None:
                raise BackendError(prompt_id,
                                   f"ComfyUI died mid-run (code {proc.returncode})")
            try:
                hist = self._http(f"/history/{prompt_id}", timeout=15)
            except Exception:
                time.sleep(POLL_S)
                continue
            entry = hist.get(prompt_id)
            if entry:
                st = entry.get("status", {})
                if st.get("completed") or st.get("status_str") == "success":
                    return entry
                if st.get("status_str") == "error":
                    raise BackendError(
                        prompt_id, json.dumps(st, ensure_ascii=False)[:1200])
            time.sleep(POLL_S)
        raise BackendError(prompt_id, f"exceeded {RUN_TIMEOUT_S}s")

    def _collect(self, entry: dict) -> list[Path]:
        root = self.comfy_root / "ComfyUI" / "output"
        found = []
        for node_out in (entry.get("outputs") or {}).values():
            for key in ("videos", "gifs", "images"):
                for item in node_out.get(key, []) or []:
                    fn = item.get("filename")
                    if fn and fn.lower().endswith(".mp4"):
                        found.append(root / (item.get("subfolder") or "") / fn)
        return found

    def render(self, episode: str, shots: Sequence[ShotSpec],
               out_dir: Path) -> list[RenderResult]:
        if self._ready():
            raise BackendError(
                "server",
                f"something is already serving on port {self.port}. Refusing to "
                f"attach to a process whose logs this run does not own -- stop "
                f"it, or point vitrine at a different port.")

        sampler = _VramSampler()
        sampler.start()
        proc = self._start()
        results: list[RenderResult] = []
        try:
            for shot in shots:
                staged = self.stage_refs(episode, shot.refs)
                wf = self.build_graph(episode, shot, staged)
                mark = len(sampler.samples)
                t0 = time.time()
                print(f"[{_now()}] >>> {shot.id}  {shot.width}x{shot.height}  "
                      f"{shot.frames}f  refs={len(staged)}", flush=True)
                entry = self._wait(self._submit(wf), proc)
                files = self._collect(entry)
                if not files:
                    raise BackendError(shot.id, "run reported success but produced no mp4")
                wall = time.time() - t0
                peak = sampler.peak_since(mark)
                print(f"[{_now()}] <<< {shot.id} ok in {wall:.1f}s, "
                      f"peak {peak} MiB", flush=True)
                results.append(RenderResult(
                    shot_id=shot.id, path=files[-1],
                    seconds_elapsed=round(wall, 1), peak_vram_mib=peak,
                    backend=self.name))
        finally:
            sampler.stop()
            proc.terminate()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
        if len(results) != len(shots):
            raise BackendError("plan", f"{len(results)} of {len(shots)} shots returned")
        return results
