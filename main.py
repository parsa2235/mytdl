import os
import re
import asyncio
import subprocess

# ۱. نصب موتور uvloop
import uvloop
uvloop.install()

# ۲. ایجاد و معرفی Event Loop به پایتون قبل از import کردن Pyrogram (رفع دقیق خطای RuntimeError)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

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
last_printed_percent = -1

def sanitize_tag_and_title(raw_input):
    title = raw_input.strip() if raw_input and raw_input.strip() else "telegram-downloads"
    tag = re.sub(r'\s+', '-', title)
    tag = re.sub(r'[\x00-\x1F\x7F~^:?*\[\\\]@{}]+', '', tag)
    if not tag:
        tag = "telegram-downloads"
    return tag, title

RELEASE_TAG, RELEASE_TITLE = sanitize_tag_and_title(RAW_RELEASE_TAG)

def reset_progress():
    global last_printed_percent
    last_printed_percent = -1

def progress(current, total):
    global last_printed_percent
    percent = int((current / total) * 100)
    if percent % 5 == 0 and percent != last_printed_percent:
        last_printed_percent = percent
        print(f"Downloading: {percent}% [{current}/{total} bytes]", flush=True)

# 🚀 سیستم دانلود موازی چندرشته‌ای چانک‌ها (Multi-Worker Parallel Downloader)
async def parallel_download_media(app, message, file_path, num_workers=10, progress_callback=None):
    file_obj = message.document or message.video or message.audio or message.photo
    if not file_obj:
        return None
        
    total_size = getattr(file_obj, "file_size", 0)
    
    if not total_size or total_size < 15 * 1024 * 1024:
        return await app.download_media(message, file_name=file_path, progress=progress_callback)

    chunk_size = 1024 * 1024
    total_chunks = (total_size + chunk_size - 1) // chunk_size

    with open(file_path, "wb") as f:
        f.truncate(total_size)

    queue = asyncio.Queue()
    for i in range(total_chunks):
        queue.put_nowait(i)

    downloaded_bytes = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal downloaded_bytes
        with open(file_path, "r+b") as f:
            while not queue.empty():
                try:
                    chunk_idx = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                success = False
                for _ in range(3):
                    try:
                        async for chunk in app.stream_media(message, offset=chunk_idx, limit=1):
                            f.seek(chunk_idx * chunk_size)
                            f.write(chunk)
                            async with lock:
                                downloaded_bytes += len(chunk)
                                if progress_callback:
                                    progress_callback(downloaded_bytes, total_size)
                            success = True
                            break
                    except Exception:
                        await asyncio.sleep(0.5)
                
                if not success:
                    queue.put_nowait(chunk_idx)

    workers = [asyncio.create_task(worker()) for _ in range(num_workers)]
    await asyncio.gather(*workers)

    return file_path

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

def upload_to_github_release(files, tag_name, release_title):
    if not files:
        return

    print(f"\n🚀 در حال آپلود به ریلیز گیتهاب ({tag_name})...", flush=True)
    subprocess.run(["gh", "release", "create", tag_name, "--title", release_title, "--notes", "Downloaded via Telegram Bot"], stderr=subprocess.DEVNULL)
    
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
                print(f"✅ {basename} آپلود و از دیسک پاک شد.", flush=True)
        else:
            print(f"❌ خطای آپلود برای {basename}", flush=True)

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
    print(f"🎯 تعداد کل پیام‌ها برای دانلود: {len(targets)}", flush=True)

    os.makedirs("downloads", exist_ok=True)

    async with Client("my_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, no_updates=True, workers=32) as app:
        for idx, (chat_id, msg_id) in enumerate(targets):
            print(f"\n==========================================", flush=True)
            print(f"📥 در حال پردازش {idx + 1} از {len(targets)}: Chat: {chat_id} | Message ID: {msg_id}", flush=True)
            try:
                message = await app.get_messages(chat_id, msg_id)
                if not message or not (message.document or message.video or message.audio or message.photo):
                    print("⚠️ این پیام حاوی فایل یا رسانه قابل دانلود نیست.", flush=True)
                    continue

                custom_name = custom_names[idx] if idx < len(custom_names) else None
                target_filename = get_target_filename(message, custom_name)
                download_path = os.path.join("downloads", target_filename)

                print(f"⏳ در حال دانلود موازی با نام: {target_filename}", flush=True)
                reset_progress()
                
                downloaded_file = await parallel_download_media(app, message, download_path, num_workers=10, progress_callback=progress)
                print(f"\n✅ دانلود موازی کامل شد: {downloaded_file}", flush=True)

                files_to_upload = split_file_if_needed(downloaded_file)
                upload_to_github_release(files_to_upload, RELEASE_TAG, RELEASE_TITLE)

            except Exception as e:
                print(f"\n❌ خطایی در پردازش پیام {msg_id} رخ داد: {e}", flush=True)

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
    loop.run_until_complete(main())
