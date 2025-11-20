# api.py
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
import asyncio, subprocess, uuid, os, requests, shlex, json, shutil, time
from pathlib import Path

app = FastAPI()

BASE_DIR = Path("static")
JOBS_DIR = Path("jobs")
BASE_DIR.mkdir(exist_ok=True)
JOBS_DIR.mkdir(exist_ok=True)

def write_json(path:Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

def read_json(path:Path):
    with open(path, "r") as f:
        return json.load(f)

async def download_file(url, out_path):
    loop = asyncio.get_event_loop()
    def _dl():
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1024*64):
                if chunk:
                    f.write(chunk)
    await loop.run_in_executor(None, _dl)
    return out_path

async def run_cmd(cmd, cwd=None):
    # returns (code, stdout, stderr)
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )
    out, err = await process.communicate()
    return process.returncode, out.decode(errors="ignore"), err.decode(errors="ignore")

@app.get("/")
async def home():
    html = Path("templates/index.html").read_text()
    return HTMLResponse(content=html, status_code=200)

@app.post("/render")
async def render_endpoint(request: Request):
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    job_id = uuid.uuid4().hex
    job_dir = JOBS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    write_json(job_dir / "payload.json", data)
    write_json(job_dir / "status.json", {"job_id": job_id, "status": "queued", "progress": 0})
    # run background
    asyncio.create_task(process_job(job_id, data))
    return JSONResponse({"job_id": job_id, "status": "processing", "video_url": f"/result/{job_id}.mp4"})

@app.get("/status/{job_id}")
async def status(job_id: str):
    status_file = JOBS_DIR / job_id / "status.json"
    if not status_file.exists():
        return JSONResponse({"job_id": job_id, "status": "not_found"}, status_code=404)
    return JSONResponse(read_json(status_file))

@app.get("/result/{file_name}")
async def result(file_name: str):
    path = BASE_DIR / file_name
    if path.exists():
        return FileResponse(path, media_type="video/mp4")
    raise HTTPException(status_code=404, detail="not_ready")

async def process_job(job_id, data):
    job_dir = JOBS_DIR / job_id
    try:
        write_json(job_dir / "status.json", {"job_id": job_id, "status": "downloading", "progress": 5})
        scenes = data.get("scenes", [])
        elements_root = data.get("elements", [])

        image_paths = []
        for i, scene in enumerate(scenes):
            els = scene.get("elements", [])
            if not els:
                continue
            img_url = els[0].get("src")
            if not img_url:
                continue
            out_img = job_dir / f"img_{i}.jpg"
            await download_file(img_url, str(out_img))
            image_paths.append({"path": str(out_img), "duration": float(scene.get("duration",5)), "transition": scene.get("transition")})

        audio_url = None
        for el in elements_root:
            if el.get("type") == "audio":
                audio_url = el.get("src")
                break
        audio_path = None
        if audio_url:
            audio_path = job_dir / "audio.mp3"
            try:
                await download_file(audio_url, str(audio_path))
            except Exception as e:
                audio_path = None

        caption_text = None
        for el in elements_root:
            if el.get("type") in ("caption","subtitles","text"):
                caption_text = el.get("text") or el.get("caption")
                break

        write_json(job_dir / "status.json", {"job_id": job_id, "status": "rendering", "progress": 15})

        # create clips
        clip_files = []
        for idx, img in enumerate(image_paths):
            out_clip = job_dir / f"clip_{idx}.mp4"
            cmd = [
                "ffmpeg","-y",
                "-loop","1","-i", img["path"],
                "-t", str(img["duration"]),
                "-vf","scale=1080:1920,format=yuv420p",
                "-c:v","libx264","-preset","veryfast","-crf","23","-r","25",
                str(out_clip)
            ]
            code,out,err = await run_cmd(cmd)
            if code != 0:
                write_json(job_dir / "status.json", {"job_id": job_id, "status": "failed", "error": err[:300]})
                return
            clip_files.append(str(out_clip))
            write_json(job_dir / "status.json", {"job_id": job_id, "status": "rendering", "progress": 15 + int((idx+1)/max(1,len(image_paths))*40)})

        if not clip_files:
            write_json(job_dir / "status.json", {"job_id": job_id, "status": "failed", "error": "no images"})
            return

        final_noaudio = job_dir / "final_noaudio.mp4"
        if len(clip_files) == 1:
            shutil.copyfile(clip_files[0], final_noaudio)
        else:
            list_txt = job_dir / "clips.txt"
            with open(list_txt, "w") as f:
                for c in clip_files:
                    f.write(f"file '{c}'\n")
            cmd = ["ffmpeg","-y","-f","concat","-safe","0","-i", str(list_txt), "-c","copy", str(final_noaudio)]
            code,out,err = await run_cmd(cmd)
            if code != 0:
                # fallback re-encode
                cmd2 = ["ffmpeg","-y","-f","concat","-safe","0","-i", str(list_txt), "-c:v","libx264","-preset","veryfast","-crf","23", str(final_noaudio)]
                code2,out2,err2 = await run_cmd(cmd2)
                if code2 != 0:
                    write_json(job_dir / "status.json", {"job_id": job_id, "status": "failed", "error": err2[:300]})
                    return

        write_json(job_dir / "status.json", {"job_id": job_id, "status": "mixing", "progress": 70})

        final_out = job_dir / f"{job_id}.mp4"
        vf_filters = []
        if caption_text:
            fontfile = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            safe_text = caption_text.replace(":", r"\:").replace("'", r"\'")
            draw = f"drawtext=fontfile={fontfile}:text='{safe_text}':fontsize=48:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=10:x=(w-text_w)/2:y=h-150"
            vf_filters.append(draw)
        vf = ",".join(vf_filters) if vf_filters else None

        if audio_path:
            cmd = ["ffmpeg","-y","-i", str(final_noaudio), "-i", str(audio_path), "-c:v","libx264","-preset","veryfast","-crf","23","-map","0:v:0","-map","1:a:0","-shortest"]
            if vf:
                cmd += ["-vf", vf]
            cmd += [str(final_out)]
        else:
            cmd = ["ffmpeg","-y","-i", str(final_noaudio), "-c:v","libx264","-preset","veryfast","-crf","23"]
            if vf:
                cmd += ["-vf", vf]
            cmd += [str(final_out)]

        code,out,err = await run_cmd(cmd)
        if code != 0:
            write_json(job_dir / "status.json", {"job_id": job_id, "status": "failed", "error": err[:400]})
            return

        # move to public static
        final_public = BASE_DIR / f"{job_id}.mp4"
        shutil.copyfile(final_out, final_public)

        write_json(job_dir / "status.json", {"job_id": job_id, "status": "done", "video_url": f"/result/{job_id}.mp4"})
    except Exception as e:
        write_json(job_dir / "status.json", {"job_id": job_id, "status": "failed", "error": str(e)})
