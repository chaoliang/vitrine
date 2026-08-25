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

The workflow template is a ComfyUI *API-format* graph, shipped with the package
at ``assets/workflows/h3_ref2va.api.json``. It wires all three reference slots
and leaves every per-shot field at a visible placeholder, so the shape of a run
is readable from the JSON. Node ids are *discovered* by class type rather than
written here as literals -- the previous version hardcoded "19" and "21", which
quietly bound the whole pipeline to one exported file from an unrelated
experiment.
"""
from __future__ import annotations

import json
import re
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

# The hub node. Everything else is found from it or by class, so a template
# with different node numbering still works.
HUB = "MiniMaxH3ReferenceToVideo"
REF_INPUT = re.compile(r"ref_images\.ref_image_(\d+)$")

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
    @staticmethod
    def _find(wf: dict, class_type: str) -> str:
        """The one node of this class. Node ids are discovered, never assumed.

        The pipeline used to name ids as string literals -- "19" for the hub,
        "21" for the seed -- which silently bound it to one exported file. Any
        H3 graph with these node types works now, whoever exported it.
        """
        hits = [k for k, v in wf.items() if v.get("class_type") == class_type]
        if len(hits) != 1:
            raise BackendError(
                "template",
                f"expected exactly one {class_type} node, found {len(hits)}"
                + (f" ({', '.join(hits)})" if hits else ""))
        return hits[0]

    @classmethod
    def _ref_slots(cls, wf: dict, hub: str) -> list[tuple[int, str]]:
        """(slot index, LoadImage node id) for every reference wired into the hub."""
        out = []
        for key, val in wf[hub]["inputs"].items():
            m = REF_INPUT.match(key)
            if m and isinstance(val, list):
                out.append((int(m.group(1)), val[0]))
        return sorted(out)

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
        """Fill the template's variable fields for one shot.

        The template ships with all three reference slots wired and every
        per-shot field left at an obvious placeholder, so the shape of the graph
        is readable from the JSON instead of having to be reconstructed from
        this method. What happens here is filling and pruning, not building.

        Pruning matters: a shot with two references must not leave a third
        LoadImage pointing at a file that was never staged. ComfyUI would reject
        the whole prompt for a missing input, and the error would name the image
        rather than the real cause.
        """
        wf = json.loads(self.workflow_template.read_text(encoding="utf-8"))
        hub = self._find(wf, HUB)
        slots = self._ref_slots(wf, hub)

        # grow the template if this shot carries more references than it wires
        while len(slots) < len(staged):
            idx = len(slots)
            nid = str(max((int(k) for k in wf if k.isdigit()), default=0) + 1)
            wf[nid] = {"class_type": "LoadImage", "inputs": {"image": ""}}
            wf[hub]["inputs"][f"ref_images.ref_image_{idx}"] = [nid, 0]
            slots.append((idx, nid))

        for (_, nid), rel in zip(slots, staged):
            wf[nid]["inputs"]["image"] = rel
        for idx, nid in slots[len(staged):]:
            del wf[hub]["inputs"][f"ref_images.ref_image_{idx}"]
            wf.pop(nid, None)

        wf[hub]["inputs"].update({
            "prompt": shot.prompt, "width": shot.width, "height": shot.height,
            "length": shot.frames,
            # measured, not the ComfyUI default: "match" drifts off the identity
            # about 2.6s in, and is slower here despite the tooltip saying otherwise
            "ref_image_size": "max"})
        wf[self._find(wf, "BasicScheduler")]["inputs"]["steps"] = shot.steps
        wf[self._find(wf, "RandomNoise")]["inputs"]["noise_seed"] = shot.seed
        wf[self._find(wf, "CreateVideo")]["inputs"]["fps"] = shot.fps
        wf[self._find(wf, "SaveVideo")]["inputs"]["filename_prefix"] = \
            f"{episode}/{shot.id}"
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
