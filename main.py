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
RELEASE_TAG = os.getenv("RELEASE_TAG", "telegram-downloads")

def parse_target_links(raw_text):
    """
    پارس کردن لینک‌ها و بازه‌ها با حافظه کانال قبلی
    پشتیبانی از:
    - https://t.me/channel/12
    - https://t.me/channel/12-15
    - https://t.me/c/12345678/10-15
    - 12-15 (استفاده از آخرین کانال دیده شده)
    """
    targets = []
    lines = raw_text.strip().split('\n')
    last_chat_id = None
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # الگوی تشخیص لینک‌های کامل تلگرام
        match = re.search(r't\.me/(?:c/)?([^/]+)/(\d+)(?:-(\d+))?', line)
        
        if match:
            chat_identifier = match.group(1)
            start_id = int(match.group(2))
            end_id = int(match.group(3)) if match.group(3) else start_id
            
            if chat_identifier.isdigit():
                chat_id = int(f"-100{chat_identifier}")
            else:
                chat_id = chat_identifier
                
            last_chat_id = chat_id  # ذخیره آخرین کانال جهت استفاده در خطوط بعدی
            
            for msg_id in range(start_id, end_id + 1):
                targets.append((chat_id, msg_id))
        else:
            # الگوی شماره یا بازه خالی مثل: 12-15 یا 20
            range_match = re.match(r'^(\d+)(?:-(\d+))?$', line)
            if range_match and last_chat_id:
                start_id = int(range_match.group(1))
                end_id = int(range_match.group(2)) if range_match.group(2) else start_id
                for msg_id in range(start_id, end_id + 1):
                    targets.append((last_chat_id, msg_id))
            else:
                print(f"⚠️ لینک یا بازه ناستباه: {line}")
                
    return targets

def progress(current, total):
    """نمایش درصد پیشرفت دانلود"""
    percent = (current / total) * 100
    print(f"\rDownloading: {percent:.1f}% [{current}/{total} bytes]", end="")

def split_file_if_needed(file_path, max_size_bytes=1900 * 1024 * 1024):
    """اگر فایل از ۱.۹ گیگ بیشتر بود آن را با 7z پارت‌بندی می‌کند"""
    if not os.path.exists(file_path):
        return []

    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]

    print(f"\n⚠️ فایل بزرگتر از حد مجاز است ({file_size / (1024**3):.2f} GB). در حال تقسیم به پارتهای 1.9GB...")
    output_archive = f"{file_path}.7z"
    
    # استفاده از فرمت 7z بدون فشرده‌سازی (-mx0) جهت حداکثر سرعت
    cmd = ["7z", "a", "-t7z", "-v1900m", "-mx0", output_archive, file_path]
    subprocess.run(cmd, check=True)
    
    # حذف فایل اصلی جهت آزاد شدن فوری دیسک
    os.remove(file_path)
    
    # پیدا کردن پارت‌های ساخته شده (like file.mp4.7z.001)
    base_dir = os.path.dirname(file_path) or "."
    archive_basename = os.path.basename(output_archive)
    parts = [os.path.join(base_dir, f) for f in os.listdir(base_dir) if f.startswith(archive_basename)]
    parts.sort()
    return parts

def upload_to_github_release(files, tag_name):
    """آپلود فایل‌ها به ریلیز گیتهاب با استفاده از GitHub CLI"""
    if not files:
        return

    print("\n🚀 در حال آپلود به ریلیز گیتهاب...")
    
    # مطمئن می‌شویم ریلیز وجود دارد
    subprocess.run(["gh", "release", "create", tag_name, "--title", f"Release {tag_name}", "--notes", "Downloaded via Telegram Bot"], stderr=subprocess.DEVNULL)
    
    for file in files:
        print(f"Uploading {file} ...")
        cmd = ["gh", "release", "upload", tag_name, file, "--clobber"]
        subprocess.run(cmd, check=True)
        # حذف پارت آپلود شده از دیسک جهت مدیریت دقیق فضا
        if os.path.exists(file):
            os.remove(file)
            print(f"✅ {file} آپلود و از دیسک پاک شد.")

async def main():
    targets = parse_target_links(LINKS_INPUT)
    if not targets:
        print("❌ هیچ لینک معتبری یافت نشد!")
        return

    print(f"🎯 تعداد کل پیام‌ها برای دانلود: {len(targets)}")

    async with Client("my_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING) as app:
        for chat_id, msg_id in targets:
            print(f"\n==========================================")
            print(f"📥 در حال پردازش: Chat: {chat_id} | Message ID: {msg_id}")
            try:
                message = await app.get_messages(chat_id, msg_id)
                if not message or not (message.document or message.video or message.audio or message.photo):
                    print("⚠️ این پیام حاوی فایل یا رسانه قابل دانلود نیست.")
                    continue

                print("⏳ در حال دانلود فایل...")
                downloaded_file = await app.download_media(message, progress=progress)
                print(f"\n✅ دانلود کامل شد: {downloaded_file}")

                # تقسیم فایل در صورت لزوم (> 1.9 GB)
                files_to_upload = split_file_if_needed(downloaded_file)

                # آپلود به ریلیز و پاکسازی فوری دیسک
                upload_to_github_release(files_to_upload, RELEASE_TAG)

            except Exception as e:
                print(f"\n❌ خطایی در پردازش پیام {msg_id} رخ داد: {e}")

if __name__ == "__main__":
    asyncio.run(main())
