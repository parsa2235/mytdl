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
    پارس کردن لینک‌ها و بازه‌ها
    پشتیبانی از:
    - https://t.me/channel/12
    - https://t.me/channel/12-15
    - https://t.me/c/12345678/10-15
    - 12-15 (در صورت وجود چنل پیش‌فرض)
    """
    targets = []
    lines = raw_text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # الگوی تشخیص لینک‌های تلگرام
        # گروه ۱: آیدی یا کانال، گروه ۲: شماره پیام شروع، گروه ۳: شماره پیام پایان (اختیاری)
        match = re.search(r't\.me/(?:c/)?([^/]+)/(\d+)(?:-(\d+))?', line)
        
        if match:
            chat_identifier = match.group(1)
            start_id = int(match.group(2))
            end_id = int(match.group(3)) if match.group(3) else start_id
            
            # اگر کانال خصوصی است (عددی است)
            if chat_identifier.isdigit():
                chat_id = int(f"-100{chat_identifier}")
            else:
                chat_id = chat_identifier
                
            for msg_id in range(start_id, end_id + 1):
                targets.append((chat_id, msg_id))
        else:
            # بررسی حالت فقط بازه عددی مثل 12-15 (نیاز به چنل ID دارد)
            range_match = re.match(r'^(\d+)-(\d+)$', line)
            if range_match:
                start_id = int(range_match.group(1))
                end_id = int(range_match.group(2))
                # چنل باید از ورودی دیگری خوانده شود یا در لینک کامل باشد
                print(f"⚠️ بازه عددی بدون کانال پشتیبانی نمی‌شود، لطفاً لینک کامل بفرستید: {line}")
                
    return targets

def progress(current, total):
    """نمایش درصد پیشرفت دانلود"""
    percent = (current / total) * 100
    print(f"\rDownloading: {percent:.1f}% [{current}/{total} bytes]", end="")

def split_file_if_needed(file_path, max_size_bytes=1900 * 1024 * 1024):
    """اگر فایل از ۱.۹ گیگ بیشتر بود آن را با 7z پارت‌بندی می‌کند"""
    file_size = os.path.getsize(file_path)
    if file_size <= max_size_bytes:
        return [file_path]

    print(f"\n⚠️ فایل بزرگتر از حد مجاز است ({file_size / (1024**3):.2f} GB). در حال تقسیم به پارتهای 1.9GB...")
    output_zip = f"{file_path}.zip"
    
    # استفاده از 7z بدون فشرده‌سازی (-mx0) برای حداکثر سرعت
    cmd = ["7z", "a", "-v1900m", "-mx0", output_zip, file_path]
    subprocess.run(cmd, check=True)
    
    # حذف فایل اصلی برای آزاد شدن دیسک
    os.remove(file_path)
    
    # پیدا کردن تمامی پارت‌های ساخته شده
    base_dir = os.path.dirname(file_path) or "."
    zip_basename = os.path.basename(output_zip)
    parts = [os.path.join(base_dir, f) for f in os.listdir(base_dir) if f.startswith(zip_basename)]
    parts.sort()
    return parts

def upload_to_github_release(files, tag_name):
    """آپلود فایل‌ها به ریلیز گیتهاب با استفاده از GitHub CLI"""
    print("\n🚀 در حال آپلود به ریلیز گیتهاب...")
    
    # مطمئن می‌شویم ریلیز وجود دارد
    subprocess.run(["gh", "release", "create", tag_name, "--title", f"Release {tag_name}", "--notes", "Downloaded via Telegram Bot"], stderr=subprocess.DEVNULL)
    
    for file in files:
        print(f"Uploading {file} ...")
        cmd = ["gh", "release", "upload", tag_name, file, "--clobber"]
        subprocess.run(cmd, check=True)
        # حذف پارت آپلود شده از دیسک جهت مدیریت فضا
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
