name: Telegram File Downloader to Release

on:
  workflow_dispatch:
    inputs:
      links:
        description: 'لینک‌های تلگرام (هر خط یک لینک یا بازه‌ای مثل 10-15)'
        required: true
        type: string
      custom_names:
        description: 'اسم‌گذاری سفارشی (مثل 1-12 یا اسامی خط‌به‌خط)'
        required: false
        type: string
      release_tag:
        description: 'نام ریلیز گیتهاب'
        required: false
        default: 'telegram-downloads'

permissions:
  contents: write

jobs:
  download-and-upload:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'
          cache: 'pip'

      - name: Install Dependencies & Tools
        run: |
          sudo apt-get update
          sudo apt-get install -y p7zip-full
          pip install -r requirements.txt

      - name: Run Telegram Downloader
        env:
          PYTHONUNBUFFERED: "1"
          TELEGRAM_API_ID: ${{ secrets.TG_API_ID }}
          TELEGRAM_API_HASH: ${{ secrets.TG_API_HASH }}
          TELEGRAM_SESSION_STRING: ${{ secrets.TG_SESSION_STRING }}
          LINKS_INPUT: ${{ inputs.links }}
          CUSTOM_NAMES_INPUT: ${{ inputs.custom_names }}
          RELEASE_TAG: ${{ inputs.release_tag }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: python main.py
