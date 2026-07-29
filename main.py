import os
import re
import asyncio
import subprocess
from pyrogram import Client

# گرفتن متغیرهای محیطی
API_ID = int(os.getenv("TELEGRAM_API_ID"))
API_HASH = os.getenv("TELEGRAM_API_HASH")
SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")
LINKS_INPUT = os.getenv("LINKS_INPUT", "")
CUSTOM_NAMES_INPUT = os.getenv("CUSTOM_NAMES_INPUT", "")
RELEASE_TAG = os.getenv("RELEASE_TAG", "telegram-downloads")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")

LINKS_FILE = "download_links.txt"

# متغیر کمکی برای چاپ درصد بدون کندی سرعت
last_printed_percent = -1

def reset_progress():
    global last_printed_percent
    last_printed_percent = -1

def progress(current, total):
    """نمایش درصد پیشرفت دانلود بدون کند کردن سیستم (چاپ روی گام‌های 5 درصدی)"""
    global last_printed_percent
    percent = int((current / total) * 100)
    if percent % 5 == 0 and percent != last_printed_percent:
        last_printed_percent = percent
        print(f"Downloading: {percent}% [{current}/{total} bytes]")

def parse_target_links(raw_text):
    """پارس کردن لینک‌ها و بازه‌ها با پشتیبانی از کانال قبلی"""
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
    """پارس کردن اسامی سفارشی (پشتیبانی از بازه 1-12 یا اسامی خط به خط)"""
    if not raw_text or not raw_text.strip():
        return []
        
    text = raw_text.strip()
    
    # تشخیص بازه عددی مانند "1-12" یا "Episode 1-12" یا "Ep 01-10"
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
        
    # در غیر این صورت اسامی چندخطی
    return [line.strip() for line in text.split('\n') if line.strip()]

def get_target_filename(message, custom_name):
    """استخراج نام اصلی یا اعمال نام سفارشی با حفظ پسوند"""
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
    """پارت‌بندی با 7z در صورت تجاوز از ۱.۹ گیگابایت"""
    if not os.path.exists(file_path):
        return []

    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]

    print(f"\n⚠️ فایل بزرگتر از حد مجاز است ({file_size / (1024**3):.2f} GB). در حال تقسیم با 7z...")
    output_archive = f"{file_path}.7z"
    
    cmd = ["7z", "a", "-t7z", "-v1900m", "-mx0", output_archive, file_path]
    subprocess.run(cmd, check=True)
    
    os.remove(file_path)
    
    base_dir = os.path.dirname(file_path) or "."
    archive_basename = os.path.basename(output_archive)
    parts = [os.path.join(base_dir, f) for f in os.listdir(base_dir) if f.startswith(archive_basename)]
    parts.sort()
    return parts

def upload_to_github_release(files, tag_name):
    """آپلود به ریلیز و ساخت لینک‌های دانلود مستقیم برای ADM"""
    if not files:
        return

    print("\n🚀 در حال آپلود به ریلیز گیتهاب...")
    subprocess.run(["gh", "release", "create", tag_name, "--title", f"Release {tag_name}", "--notes", "Downloaded via Telegram Bot"], stderr=subprocess.DEVNULL)
    
    for file in files:
        basename = os.path.basename(file)
        print(f"Uploading {basename} ...")
        cmd = ["gh", "release", "upload", tag_name, file, "--clobber"]
        subprocess.run(cmd, check=True)
        
        # ذخیره لینک دانلود مستقیم برای ADM
        if GITHUB_REPOSITORY:
            direct_url = f"https://github.com/{GITHUB_REPOSITORY}/releases/download/{tag_name}/{basename}"
            with open(LINKS_FILE, "a", encoding="utf-8") as f:
                f.write(direct_url + "\n")
        
        if os.path.exists(file):
            os.remove(file)
            print(f"✅ {basename} آپلود و از دیسک پاک شد.")

async def main():
    # پاک کردن فایل لینک‌های قدیمی قبل از شروع اجرا
    if os.path.exists(LINKS_FILE):
        os.remove(LINKS_FILE)

    targets = parse_target_links(LINKS_INPUT)
    custom_names = parse_custom_names(CUSTOM_NAMES_INPUT)

    if not targets:
        print("❌ هیچ لینک معتبری یافت نشد!")
        return

    print(f"🎯 تعداد کل پیام‌ها برای دانلود: {len(targets)}")

    os.makedirs("downloads", exist_ok=True)

    async with Client("my_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, workers=32) as app:
        for idx, (chat_id, msg_id) in enumerate(targets):
            print(f"\n==========================================")
            print(f"📥 در حال پردازش {idx + 1} از {len(targets)}: Chat: {chat_id} | Message ID: {msg_id}")
            try:
                message = await app.get_messages(chat_id, msg_id)
                if not message or not (message.document or message.video or message.audio or message.photo):
                    print("⚠️ این پیام حاوی فایل یا رسانه قابل دانلود نیست.")
                    continue

                custom_name = custom_names[idx] if idx < len(custom_names) else None
                target_filename = get_target_filename(message, custom_name)
                download_path = os.path.join("downloads", target_filename)

                print(f"⏳ در حال دانلود با نام: {target_filename}")
                reset_progress()
                downloaded_file = await app.download_media(message, file_name=download_path, progress=progress)
                print(f"\n✅ دانلود کامل شد: {downloaded_file}")

                files_to_upload = split_file_if_needed(downloaded_file)
                upload_to_github_release(files_to_upload, RELEASE_TAG)

            except Exception as e:
                print(f"\n❌ خطایی در پردازش پیام {msg_id} رخ داد: {e}")

    # در صورت وجود فایل لینک‌ها، آن را هم به ریلیز آپلود کن و در لاگ چاپ کن
    if os.path.exists(LINKS_FILE) and os.path.getsize(LINKS_FILE) > 0:
        print("\n==========================================")
        print("🔗 لیست تمامی لینک‌های مستقیم ایجادشده برای ADM:")
        print("==========================================")
        with open(LINKS_FILE, "r", encoding="utf-8") as f:
            content = f.read()
            print(content)
        
        # آپلود فایل txt به ریلیز
        subprocess.run(["gh", "release", "upload", RELEASE_TAG, LINKS_FILE, "--clobber"], check=True)
        print("✅ فایل download_links.txt به ریلیز گیتهاب اضافه شد!")

if __name__ == "__main__":
    asyncio.run(main())
