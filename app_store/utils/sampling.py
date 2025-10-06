import os, time, pathlib

SAMPLES_DIR = os.getenv("SAMPLES_DIR", "app_store/samples")

def save_channel_sample(channel_id: int, message_id: int, title: str|None, text: str|None):
    pathlib.Path(SAMPLES_DIR).mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    base = f"{channel_id}_{message_id}_{ts}"
    meta_path = os.path.join(SAMPLES_DIR, f"{base}.meta.txt")
    lines_path = os.path.join(SAMPLES_DIR, f"{base}.lines.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"title: {title or ''}\n")
        f.write(f"channel_id: {channel_id}\nmessage_id: {message_id}\n")
    if text:
        with open(lines_path, "w", encoding="utf-8") as f:
            for ln in text.splitlines():
                if ln.strip():
                    f.write(ln.rstrip()+"\n")
    return lines_path
