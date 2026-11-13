
from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path



def parse_sidecar(path: str | Path) -> dict:

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    for i, ev in enumerate(data.get("events", [])):
        for key in ("t", "x", "y"):
            if key not in ev:
                raise ValueError(f"Event {i} missing '{key}': {ev}")

    return {
        "viewport":    data.get("viewport", {"width": 1280, "height": 720}),
        "fps":         data.get("fps", 25),
        "zoom_factor": data.get("zoom_factor", 2.0),
        "ramp_sec":    data.get("ramp_sec", 0.5),
        "events":      data.get("events", []),
    }


def pair_events(events: list[dict]) -> list[tuple[dict, dict | None]]:

    norm: list[dict] = []
    next_t = "in"
    for ev in events:
        e = dict(ev)
        if "type" not in e:
            e["type"] = next_t
            next_t = "out" if next_t == "in" else "in"
        norm.append(e)

    pairs: list[tuple[dict, dict | None]] = []
    i = 0
    while i < len(norm):
        if norm[i]["type"] != "in":
            i += 1
            continue

        in_ev = norm[i]
        out_ev = None
        for j in range(i + 1, len(norm)):
            if norm[j]["type"] == "out":
                out_ev = norm[j]
                i = j + 1
                break
        else:
            i += 1

        pairs.append((in_ev, out_ev))

    return pairs



def smoothstep(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3.0 - 2.0 * t)



def compute_frame_params(
    frame: int,
    pairs: list[tuple[dict, dict | None]],
    fps: float,
    zoom_factor: float,
    ramp_sec: float,
    width: int,
    height: int,
) -> tuple[float, float, float]:

    t = frame / fps
    zoom = 1.0
    cx, cy = width / 2.0, height / 2.0

    for in_ev, out_ev in pairs:
        t_in     = in_ev["t"]
        t_in_end = t_in + ramp_sec
        t_out     = out_ev["t"] if out_ev else float("inf")
        t_out_end = t_out + ramp_sec

        if t < t_in:
            continue

        px, py = float(in_ev["x"]), float(in_ev["y"])

        if t < t_in_end:
            p = (t - t_in) / ramp_sec if ramp_sec else 1.0
            zoom = 1.0 + (zoom_factor - 1.0) * smoothstep(p)
            cx, cy = px, py
            break
        if t < t_out:
            zoom = zoom_factor
            cx, cy = px, py
            break
        if t < t_out_end:
            p = (t - t_out) / ramp_sec if ramp_sec else 1.0
            zoom = zoom_factor - (zoom_factor - 1.0) * smoothstep(p)
            cx, cy = px, py
            break

    if zoom > 1.0:
        cw = width / zoom
        ch = height / zoom
        x = max(0.0, min(cx - cw / 2, width - cw))
        y = max(0.0, min(cy - ch / 2, height - ch))
    else:
        x = y = 0.0

    return zoom, x, y



def _ss_expr(start: int, length: int) -> str:
    if length <= 0:
        return "1"
    p = f"((in-{start})/{length})"
    return f"(3*{p}*{p}-2*{p}*{p}*{p})"


def build_filter(
    pairs: list[tuple[dict, dict | None]],
    fps: float,
    zoom_factor: float,
    ramp_sec: float,
    total_frames: int,
    width: int,
    height: int,
) -> str | None:

    ramp_f = int(round(ramp_sec * fps))
    zf = zoom_factor

    segs: list[tuple[int, int, str, int, int]] = []

    for in_ev, out_ev in pairs:
        f_in = int(round(in_ev["t"] * fps))
        f_re  = f_in + ramp_f
        px, py = int(in_ev["x"]), int(in_ev["y"])

        if ramp_f > 0:
            ss = _ss_expr(f_in, ramp_f)
            segs.append((f_in, f_re - 1, f"1+{zf - 1}*{ss}", px, py))

        if out_ev is not None:
            f_out = int(round(out_ev["t"] * fps))
            hold_end = f_out - 1
        else:
            hold_end = total_frames - 1
            f_out = None

        if f_re <= hold_end:
            segs.append((f_re, hold_end, str(zf), px, py))

        if f_out is not None and ramp_f > 0:
            ss = _ss_expr(f_out, ramp_f)
            segs.append((f_out, f_out + ramp_f - 1,
                         f"{zf}-{zf - 1}*{ss}", px, py))

    if not segs:
        return None

    z = "1"
    x = "0"
    y = "0"
    for s, e, ze, px, py in reversed(segs):
        z = f"if(between(in,{s},{e}),{ze},{z})"
        x = f"if(between(in,{s},{e}),clip({px}-iw/(2*zoom),0,iw-iw/zoom),{x})"
        y = f"if(between(in,{s},{e}),clip({py}-ih/(2*zoom),0,ih-ih/zoom),{y})"

    return (
        f"zoompan=z='{z}':x='{x}':y='{y}'"
        f":d=1:s={width}x{height}:fps={int(fps)}"
    )



def get_video_info(
    path: str | Path,
    ffprobe_bin: str = "ffprobe",
    fallback: dict | None = None,
) -> dict:
    try:
        cmd = [
            ffprobe_bin, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(res.stdout)

        st = data["streams"][0]
        w, h = int(st["width"]), int(st["height"])

        num, den = (int(x) for x in st.get("r_frame_rate", "25/1").split("/"))
        fps = num / den if den else 25.0

        nb = st.get("nb_frames")
        if nb and nb != "N/A":
            total = int(nb)
        else:
            dur = float(
                st.get("duration")
                or data.get("format", {}).get("duration", 0)
            )
            total = int(dur * fps)

        return {"width": w, "height": h, "fps": fps, "total_frames": total}
    except Exception as err:
        if fallback:
            return fallback
        raise



def build_ffmpeg_cmd(
    video: str,
    output: str,
    vf: str,
    ffmpeg_bin: str = "ffmpeg",
) -> list[str]:
    return [
        ffmpeg_bin, "-y",
        "-i", video,
        "-vf", vf,
        "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
        "-c:a", "copy",
        output,
    ]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Apply Camtasia-style zoom to a recorded video.")
    ap.add_argument("--video",   required=True,
                    help="Path to the input .webm video.")
    ap.add_argument("--sidecar", default=None,
                    help="Path to the .zoom.json sidecar (default: <stem>.zoom.json).")
    ap.add_argument("--output",  default=None,
                    help="Output path (default: <stem>_zoomed.webm).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the ffmpeg command without running it.")
    ap.add_argument("--ffmpeg",  default="ffmpeg",
                    help="Path to the ffmpeg binary.")
    args = ap.parse_args(argv)

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"Error: video not found: {video}")

    out = (Path(args.output) if args.output
           else video.parent / f"{video.stem}_zoomed{video.suffix}")

    sidecar_path = Path(args.sidecar) if args.sidecar else video.parent / f"{video.stem}.zoom.json"

    if not sidecar_path.exists():
        print(f"No sidecar at {sidecar_path}; copying unchanged to {out}.")
        shutil.copy2(video, out)
        return

    sc = parse_sidecar(sidecar_path)
    if not sc["events"]:
        print(f"Sidecar has no events; copying unchanged to {out}.")
        shutil.copy2(video, out)
        return

    pairs = pair_events(sc["events"])

    ffprobe_bin = "ffprobe"
    if args.ffmpeg != "ffmpeg":
        cand = Path(args.ffmpeg).parent / ("ffprobe" + Path(args.ffmpeg).suffix)
        if cand.exists():
            ffprobe_bin = str(cand)

    vp = sc.get("viewport", {})
    max_t = max((float(e.get("t", 0)) for e in sc["events"]), default=10.0)
    fallback_info = {
        "width": int(vp.get("width", 1280)),
        "height": int(vp.get("height", 720)),
        "fps": float(sc.get("fps", 25.0)),
        "total_frames": int(round((max_t + 10.0) * float(sc.get("fps", 25.0)))),
    }
    info = get_video_info(video, ffprobe_bin, fallback=fallback_info)

    vf = build_filter(
        pairs,
        fps=sc["fps"],
        zoom_factor=sc["zoom_factor"],
        ramp_sec=sc["ramp_sec"],
        total_frames=info["total_frames"],
        width=info["width"],
        height=info["height"],
    )
    if vf is None:
        print(f"No zoom segments; copying unchanged to {out}.")
        shutil.copy2(video, out)
        return

    cmd = build_ffmpeg_cmd(str(video), str(out), vf, args.ffmpeg)

    if args.dry_run:
        print(shlex.join(cmd))
        return

    print(f"Processing {video} -> {out} ...")
    subprocess.run(cmd, check=True)
    print(f"Done -> {out}")


if __name__ == "__main__":
    main()
