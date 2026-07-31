import os
import re
import time
import asyncio
import threading
import subprocess
from pyrogram import Client

ACCOUNT_CHOICE = os.getenv("ACCOUNT_CHOICE", "Account 1")

if "2" in ACCOUNT_CHOICE:
    API_ID = int(os.getenv("TG_API_ID_2") or 0)
    API_HASH = os.getenv("TG_API_HASH_2")
    SESSION_STRING = os.getenv("TG_SESSION_STRING_2")
elif "3" in ACCOUNT_CHOICE:
    API_ID = int(os.getenv("TG_API_ID_3") or 0)
    API_HASH = os.getenv("TG_API_HASH_3")
    SESSION_STRING = os.getenv("TG_SESSION_STRING_3")
else:
    API_ID = int(os.getenv("TG_API_ID_1") or os.getenv("TELEGRAM_API_ID") or 0)
    API_HASH = os.getenv("TG_API_HASH_1") or os.getenv("TELEGRAM_API_HASH")
    SESSION_STRING = os.getenv("TG_SESSION_STRING_1") or os.getenv("TELEGRAM_SESSION_STRING")

LINKS_INPUT = os.getenv("LINKS_INPUT", "")
CUSTOM_NAMES_INPUT = os.getenv("CUSTOM_NAMES_INPUT", "")
RAW_RELEASE_TAG = os.getenv("RELEASE_TAG", "telegram-downloads")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")

LINKS_FILE = "download_links.txt"

# 📊 حافظه سنکرون ردیابی سرجمع تمام فایل‌های همزمان (Thread-Safe)
task_downloaded = {}
task_total_size = {}
tracker_lock = threading.Lock()

last_report_time = time.time()
last_report_bytes = 0
last_reported_percent = -1

def sanitize_tag_and_title(raw_input):
    title = raw_input.strip() if raw_input and raw_input.strip() else "telegram-downloads"
    tag = re.sub(r'\s+', '-', title)
    tag = re.sub(r'[\x00-\x1F\x7F~^:?*\[\\\]@{}]+', '', tag)
    if not tag:
        tag = "telegram-downloads"
    return tag, title

RELEASE_TAG, RELEASE_TITLE = sanitize_tag_and_title(RAW_RELEASE_TAG)

def parse_target_links(raw_text):
    targets = []
    lines = raw_text.strip().split('\n')
    last_chat_id = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        match = re.search(r't\.me/(?:c/)?([^/]+)/(\d+)(?:-(\d+))?', line)
        
        if match:
            chat_identifier = match.group(1)
            start_id = int(match.group(2))
            end_id = int(match.group(3)) if match.group(3) else start_id
            
            if chat_identifier.isdigit():
                chat_id = int(f"-100{chat_identifier}")
            else:
                chat_id = chat_identifier
                
            last_chat_id = chat_id
            for msg_id in range(start_id, end_id + 1):
                targets.append((chat_id, msg_id))
        else:
            range_match = re.match(r'^(\d+)(?:-(\d+))?$', line)
            if range_match and last_chat_id:
                start_id = int(range_match.group(1))
                end_id = int(range_match.group(2)) if range_match.group(2) else start_id
                for msg_id in range(start_id, end_id + 1):
                    targets.append((last_chat_id, msg_id))
                
    return targets

def parse_custom_names(raw_text):
    if not raw_text or not raw_text.strip():
        return []
        
    text = raw_text.strip()
    range_match = re.match(r'^(.*?)\s*(\d+)-(\d+)$', text)
    if range_match:
        prefix = range_match.group(1).strip()
        start_str = range_match.group(2)
        end = int(range_match.group(3))
        start = int(start_str)
        
        pad_length = len(start_str) if start_str.startswith('0') and len(start_str) > 1 else 0
        
        names = []
        for i in range(start, end + 1):
            num_str = str(i).zfill(pad_length) if pad_length > 0 else str(i)
            name = f"{prefix} {num_str}".strip() if prefix else num_str
            names.append(name)
        return names
        
    return [line.strip() for line in text.split('\n') if line.strip()]

def get_target_filename(message, custom_name):
    file_obj = message.document or message.video or message.audio or message.photo
    original_name = getattr(file_obj, "file_name", None) or "file.bin"
    _, ext = os.path.splitext(original_name)
    
    if not custom_name:
        return original_name
        
    c_base, c_ext = os.path.splitext(custom_name)
    if c_ext:
        return custom_name
    else:
        return f"{custom_name}{ext}"

def split_file_if_needed(file_path, max_size_bytes=1900 * 1024 * 1024):
    if not os.path.exists(file_path):
        return []

    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]

    print(f"\n⚠️ فایل بزرگتر از حد مجاز است ({file_size / (1024**3):.2f} GB). در حال تقسیم با 7z...", flush=True)
    output_archive = f"{file_path}.7z"
    
    cmd = ["7z", "a", "-t7z", "-v1900m", "-mx0", output_archive, file_path]
    subprocess.run(cmd, check=True)
    
    os.remove(file_path)
    
    base_dir = os.path.dirname(file_path) or "."
    archive_basename = os.path.basename(output_archive)
    parts = [os.path.join(base_dir, f) for f in os.listdir(base_dir) if f.startswith(archive_basename)]
    parts.sort()
    return parts

upload_lock = asyncio.Lock()

async def upload_to_github_release_async(files, tag_name, release_title):
    if not files:
        return

    async with upload_lock:
        print(f"\n🚀 شروع آپلود به ریلیز گیتهاب ({tag_name})...", flush=True)
        subprocess.run(["gh", "release", "create", tag_name, "--title", release_title, "--notes", "Downloaded via Pyrogram Bot"], stderr=subprocess.DEVNULL)
        
        for file in files:
            basename = os.path.basename(file)
            print(f"Uploading {basename} ...", flush=True)
            cmd = ["gh", "release", "upload", tag_name, file, "--clobber"]
            res = subprocess.run(cmd)
            
            if res.returncode == 0:
                if GITHUB_REPOSITORY:
                    direct_url = f"https://github.com/{GITHUB_REPOSITORY}/releases/download/{tag_name}/{basename}"
                    with open(LINKS_FILE, "a", encoding="utf-8") as f:
                        f.write(direct_url + "\n")
                
                if os.path.exists(file):
                    os.remove(file)
                    print(f"✅ آپلود تمام شد: {basename} (از دیسک پاک شد)", flush=True)
            else:
                print(f"❌ خطای آپلود برای {basename}", flush=True)

# 📊 گزارش‌گر سنکرون سرجمع کل (Thread-Safe برای تردهای پایرگرام)
def update_aggregate_progress(task_idx, current, total):
    global last_report_time, last_report_bytes, last_reported_percent

    with tracker_lock:
        task_downloaded[task_idx] = current
        task_total_size[task_idx] = total

        sum_downloaded = sum(task_downloaded.values())
        sum_total = sum(task_total_size.values())

        if sum_total == 0:
            return

        percent = int((sum_downloaded / sum_total) * 100)
        now = time.time()
        time_diff = now - last_report_time

        if percent % 10 == 0 and percent != last_reported_percent and percent <= 100:
            last_reported_percent = percent

            speed_bytes_sec = 0
            if time_diff > 0:
                speed_bytes_sec = (sum_downloaded - last_report_bytes) / time_diff

            speed_mb = speed_bytes_sec / (1024 * 1024)

            eta_str = "..."
            if speed_bytes_sec > 0:
                remaining_bytes = sum_total - sum_downloaded
                eta_sec = int(remaining_bytes / speed_bytes_sec)
                m, s = divmod(eta_sec, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    eta_str = f"{h}h {m}m {s}s"
                elif m > 0:
                    eta_str = f"{m}m {s}s"
                else:
                    eta_str = f"{s}s"

            last_report_time = now
            last_report_bytes = sum_downloaded

            curr_mb = sum_downloaded / (1024 * 1024)
            total_mb = sum_total / (1024 * 1024)

            completed_files = sum(1 for idx in task_downloaded if task_downloaded[idx] >= task_total_size[idx] and task_total_size[idx] > 0)
            total_files_count = len(task_total_size)

            print(
                f"📊 [پیشرفت کل] {percent}% [{curr_mb:.1f}/{total_mb:.1f} MB] "
                f"| سرعت کل: {speed_mb:.2f} MB/s "
                f"| زمان باقی‌مانده: {eta_str} "
                f"| ({completed_files}/{total_files_count} فایل)",
                flush=True
            )

async def process_single_target(app, idx, total_count, chat_id, msg_id, custom_name):
    try:
        message = await app.get_messages(chat_id, msg_id)
        if not message or not (message.document or message.video or message.audio or message.photo):
            print(f"⚠️ پیام {msg_id} حاوی فایل قابل دانلود نیست.", flush=True)
            return

        target_filename = get_target_filename(message, custom_name)
        download_path = os.path.join("downloads", f"task_{idx}_{target_filename}")

        def progress_wrapper(current, total):
            update_aggregate_progress(idx, current, total)

        downloaded_file = await app.download_media(message, file_name=download_path, progress=progress_wrapper)

        final_path = os.path.join("downloads", target_filename)
        if os.path.exists(downloaded_file):
            os.rename(downloaded_file, final_path)
            downloaded_file = final_path

        print(f"\n✅ دانلود فایل کامل شد: {target_filename} ➔ شروع بلافاصله آپلود...", flush=True)

        files_to_upload = split_file_if_needed(downloaded_file)
        await upload_to_github_release_async(files_to_upload, RELEASE_TAG, RELEASE_TITLE)

    except Exception as e:
        print(f"\n❌ خطایی در پردازش پیام {msg_id} رخ داد: {e}", flush=True)

async def main():
    if os.path.exists(LINKS_FILE):
        os.remove(LINKS_FILE)

    targets = parse_target_links(LINKS_INPUT)
    custom_names = parse_custom_names(CUSTOM_NAMES_INPUT)

    if not targets:
        print("❌ هیچ لینک معتبری یافت نشد!", flush=True)
        return

    print(f"👤 اکانت فعال انتخاب‌شده: {ACCOUNT_CHOICE}", flush=True)
    print(f"🏷️ نام ریلیز: {RELEASE_TITLE} (Tag: {RELEASE_TAG})", flush=True)
    print(f"🎯 تعداد کل پیام‌ها برای دانلود همزمان و بدون محدودیت: {len(targets)}", flush=True)

    os.makedirs("downloads", exist_ok=True)

    async with Client("my_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, no_updates=True, workers=32) as app:
        tasks = []
        for idx, (chat_id, msg_id) in enumerate(targets):
            custom_name = custom_names[idx] if idx < len(custom_names) else None
            task = asyncio.create_task(process_single_target(app, idx, len(targets), chat_id, msg_id, custom_name))
            tasks.append(task)

        await asyncio.gather(*tasks)

    if os.path.exists(LINKS_FILE) and os.path.getsize(LINKS_FILE) > 0:
        print("\n==========================================", flush=True)
        print("🔗 لیست تمامی لینک‌های مستقیم ایجادشده برای ADM:", flush=True)
        print("==========================================", flush=True)
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            print(content, flush=True)
        
        subprocess.run(["gh", "release", "upload", RELEASE_TAG, LINKS_FILE, "--clobber"], check=True)
        print("✅ فایل download_links.txt به ریلیز گیتهاب اضافه شد!", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
