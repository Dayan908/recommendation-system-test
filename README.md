---
title: Recommendation System
emoji: 🐨
colorFrom: blue
colorTo: red
sdk: gradio
sdk_version: 4.43.0
app_file: app.py
pinned: false
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference

# 智慧照顧產品推薦系統

這是一個基於 ChatGPT 的智慧照顧產品推薦系統，可以根據用戶需求推薦合適的照顧產品。

## 功能特點

- 智能產品推薦
- 多步驟對話式推薦流程
- 郵件發送推薦結果
- 響應式網頁界面
- 用戶反饋表單

## 本地開發

1. 克隆專案
```bash
git clone [repository-url]
cd [project-directory]
```

2. 安裝依賴
```bash
pip install -r requirements.txt
```

3. 配置環境變數
創建 `.env` 文件並添加以下內容：
```
OPENAI_API_KEY=your_openai_api_key
EMAIL_SENDER=your_email@gmail.com
EMAIL_PASSWORD=your_email_app_password
```

4. 運行應用
```bash
python app.py
```

## Render 部署

1. 在 Render 上創建新的 Web Service
2. 連接 GitHub 倉庫
3. 配置以下環境變數：
   - `OPENAI_API_KEY`
   - `EMAIL_SENDER`
   - `EMAIL_PASSWORD`
4. 選擇 Python 運行環境
5. 設置啟動命令：`python app.py`

## 注意事項

- 請確保 OpenAI API 密鑰有效
- 使用 Gmail 發送郵件時需要使用應用密碼
- 建議定期備份數據
- 請遵守 OpenAI 的使用政策

## 免責聲明

本系統應用 ChatGPT 進行智慧照顧產品推薦，提供之產品資訊僅供參考，使用者應自行前往各產品的官方網頁確認詳細資訊及最新規格。
