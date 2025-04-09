import openai
import gradio as gr
import pandas as pd
import os
import smtplib
import logging
from datetime import datetime
from dotenv import load_dotenv
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# 設置日誌記錄
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)

# 載入環境變數
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# 全局變數
conversation = []
current_step = "步驟零"

def load_excel_data():
    try:
        file_path = 'GPTdata0325.xlsx'
        if not os.path.exists(file_path):
            logging.error(f"找不到檔案: {file_path}")
            raise FileNotFoundError(f"找不到檔案: {file_path}")
        
        df = pd.read_excel(file_path)
        if df.empty:
            logging.error("Excel 檔案是空的")
            raise ValueError("Excel 檔案是空的")
            
        required_columns = ['產品名稱', '公司名稱', '公司地址', '連絡電話', '產品網址', 
                          '主要功能', '使用方式', '產品第一層分類', '產品第二層分類']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logging.error(f"Excel 檔案缺少必要欄位: {', '.join(missing_columns)}")
            raise ValueError(f"Excel 檔案缺少必要欄位: {', '.join(missing_columns)}")
            
        logging.info("成功載入Excel數據")
        return df
    except Exception as e:
        logging.error(f"載入Excel數據時發生錯誤: {str(e)}")
        raise

# 載入產品數據
try:
    df = load_excel_data()
    # 建立產品分類緩存
    product_categories = {}
    for _, row in df.iterrows():
        category = row['產品第一層分類']
        if category not in product_categories:
            product_categories[category] = []
        product_categories[category].append(row.to_dict())
except Exception as e:
    logging.error(f"初始化數據時發生錯誤: {str(e)}")
    raise

def get_category_products(category):
    """獲取特定分類的產品數據"""
    if category in product_categories:
        return product_categories[category]
    return []

def query_chatgpt(user_input, state, email):
    global conversation, current_step
    
    try:
        # 基礎系統提示
        base_system_prompt = """
# 角色與目標
你是智慧照顧產品推薦專家。你的任務是根據客戶的需求，從下方提供的產品資料中，為客戶推薦合適的智慧照顧產品。

# 重要限制
- 絕對禁止提及或暗示你參考的資料來源。
- 所有推薦必須自然呈現，如同基於你的專業知識。
- 請嚴格依照以下推薦流程步驟進行。
- 任何對話都必須使用繁體中文亦或是使用者使用的語言。

# 推薦流程步驟

## 步驟零：啟動與重置
- 當客戶表達「開始新諮詢的意圖」時，視為啟動全新的推薦流程
  - 例如：說「你好」、「我想找產品」、「請推薦」、「重新開始」等類似語句
- 準備好從資料來源讀取信息，並等待客戶提出初步需求
- 以友善的招呼語開始，例如：
  「您好！我是智慧照顧產品推薦專家，請問您在尋找哪方面的協助或產品呢？」

## 步驟一：確認第一層分類
- 根據客戶的簡短需求，判斷最可能屬於哪一個「產品第一層分類」
- 向客戶說明判斷的分類，並解釋該分類包含的產品類型
- 詢問此方向是否符合客戶需求
- 必須先完成此分類確認，請勿直接跳至第二層分類
- 對話範例：
  「聽起來您可能在尋找與『居家安全監控』相關的產品，這類產品通常用於偵測跌倒、異常離床或提供緊急呼叫功能。請問這個方向是您想要的嗎？」

## 步驟二：探索第二層分類需求
- 在確認第一層分類後，仔細閱讀該分類下所有產品的功能和使用方式
- 根據產品差異，提出具體問題引導客戶
- 問題可圍繞：
  - 功能偏好
  - 使用場景
  - 操作方式
- 對話範例：
  「為了更精確地推薦，請問您：
  1. 比較重視『自動偵測並發出警報』（如跌倒偵測），還是『主動求助』（如緊急按鈕）的功能？
  2. 對於安裝方式（固定式或穿戴式）您有特別偏好嗎？」

## 步驟三：統整與確認需求
- 統整所有需求資訊
- 指出對應的「產品第二層分類」
- 向客戶複述完整需求並請求確認
- 確認範例：
  「好的，讓我整理一下您的需求：
  - 第一層分類：『居家安全監控』
  - 特別需求：『自動偵測異常狀態，如跌倒』功能
  - 偏好：非穿戴式設備
  請問我的理解正確嗎？」

## 步驟四：提供產品推薦
- 在確認需求無誤後，從下方提供的「產品資訊」中篩選最符合的產品。
- 至少推薦三項產品。
- **對於每項推薦的產品，請務必使用提供的完整資訊，包含：**
  1.  **產品名稱**
  2.  **公司名稱**
  3.  **主要功能與特色**
  4.  **產品網址**
  5.  **廠商連絡電話**

## 步驟五：滿意度詢問與後續
- 詢問：「請問以上推薦的產品是否符合您的期待？」
- 如果滿意：
  「如果您對這次的推薦感到滿意，請在下方提供您的電子郵件地址，我會將推薦結果整理後寄送給您。」
- 如果不滿意：
  - 回到步驟二重新詢問需求。
  - 必要時回到步驟一重新確認分類。
  - 根據新資訊調整推薦。
"""

        # 獲取相關產品資訊
        relevant_products = []
        if "current_category" in state and state["current_category"]:
            # 如果已經確定了分類，獲取該分類的所有產品
            products = product_categories.get(state["current_category"], [])
            relevant_products.extend(products)
        else:
            # 如果還沒有確定分類，獲取所有產品
            for category, products in product_categories.items():
                relevant_products.extend(products)  # 獲取所有產品，不限制數量

        # 將產品資訊轉換為更清晰的格式
        products_info = []
        for product in relevant_products:
            product_info = (
                f"產品名稱：{product.get('產品名稱', 'N/A')}\n"
                f"公司名稱：{product.get('公司名稱', 'N/A')}\n"
                f"主要功能：{product.get('主要功能', 'N/A')}\n"
                f"使用方式：{product.get('使用方式', 'N/A')}\n"
                f"產品網址：{product.get('產品網址', 'N/A')}\n"
                f"連絡電話：{product.get('連絡電話', 'N/A')}\n"
                f"分類：{product.get('產品第一層分類', 'N/A')} > {product.get('產品第二層分類', 'N/A')}\n"
                f"---"
            )
            products_info.append(product_info)

        # 添加分類資訊
        categories_info = "可用分類：\n" + "\n".join([f"- {cat}" for cat in product_categories.keys()])
        
        # 組合完整的system prompt
        system_prompt = (
            base_system_prompt + "\n\n" +
            categories_info + "\n\n" +
            "==== 產品資訊 ====\n" + "\n".join(products_info) + "\n==== 產品資訊結束 ===="
        )

        conversation.append({"role": "user", "content": user_input})

        response = openai.ChatCompletion.create(
            model="gpt-4o-2024-08-06",
            messages=[
                {"role": "user", "content": system_prompt},
                {"role": "user", "content": f"目前進行：{current_step}"},
                *conversation
            ]
        )

        reply = response['choices'][0]['message']['content']
        conversation.append({"role": "assistant", "content": reply})

        # 更新當前分類（如果在回覆中提到）
        for category in product_categories.keys():
            if category in reply:
                state["current_category"] = category
                break

        state["recommendations"] = reply
        state["email_content"] = reply

        conversation_history = [(conversation[i]['content'], conversation[i+1]['content']) 
                              for i in range(0, len(conversation) - 1, 2)]

        logging.info("成功生成推薦回應")
        return conversation_history, state

    except Exception as e:
        logging.error(f"生成推薦時發生錯誤: {str(e)}")
        error_message = "抱歉，系統暫時無法處理您的請求，請稍後再試。"
        return [(user_input, error_message)], state

def send_email(to_email, subject, body):
    try:
        sender_email = os.getenv("EMAIL_SENDER")
        sender_password = os.getenv("EMAIL_PASSWORD")
        
        # 添加環境變數檢查
        if not sender_email:
            logging.error("EMAIL_SENDER 環境變數未設置")
            return "郵件設定錯誤：寄件者郵箱未設置"
        if not sender_password:
            logging.error("EMAIL_PASSWORD 環境變數未設置")
            return "郵件設定錯誤：寄件者密碼未設置"
            
        logging.info(f"嘗試使用郵箱帳號: {sender_email}")
        
        smtp_server = "smtp.gmail.com"
        smtp_port = 587

        disclaimer = "\n\n免責聲明: 本系統僅為參考，所有產品資訊請以實際產品網頁為主，詳細信息請查閱相關網站。"

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = to_email
        msg["Subject"] = subject

        body_with_disclaimer = body + disclaimer
        msg.attach(MIMEText(body_with_disclaimer, "plain"))

        try:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            logging.info("正在嘗試登入 SMTP 伺服器...")
            server.login(sender_email, sender_password)
            logging.info("SMTP 伺服器登入成功")
            server.sendmail(sender_email, to_email, msg.as_string())
            server.quit()
            logging.info(f"成功發送郵件至 {to_email}")
            return "郵件已成功發送"
        except smtplib.SMTPAuthenticationError as e:
            logging.error(f"SMTP 認證錯誤: {str(e)}")
            return f"郵件發送失敗: SMTP 認證錯誤，請檢查郵箱設定"
        except Exception as e:
            logging.error(f"SMTP 錯誤: {str(e)}")
            return f"郵件發送失敗: {str(e)}"
            
    except Exception as e:
        logging.error(f"發送郵件時發生錯誤: {str(e)}")
        return f"郵件發送失敗: {str(e)}"

def interact(user_input, state, email):
    chat_history, state = query_chatgpt(user_input, state, email)
    return chat_history, state, ""

def gradio_interface(user_input, email, state):
    if state is None:
        state = {
            "step": 0,
            "top_matches": None,
            "products_info": None,
            "recommendations": "",
            "email_content": "",
            "chat_history": [],
            "current_category": None
        }
    return interact(user_input, state, email)

# Gradio Blocks UI
with gr.Blocks(
    theme=gr.themes.Soft(),  # 使用柔和主題
    css="""
    /* 整體容器 */
    .container { 
        max-width: 1200px;
        margin: 0 auto;
        padding: 20px;
        background-color: #f8f9fa;
        border-radius: 15px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }

    /* 深色模式適配 */
    @media (prefers-color-scheme: dark) {
        .container {
            background-color: #2d2d2d;
            color: #e0e0e0;
        }
        
        .header {
            background: linear-gradient(135deg, #3d3d3d 0%, #2d2d2d 100%);
            color: #e0e0e0;
        }
        
        .disclaimer {
            background-color: rgba(60, 60, 60, 0.9) !important;
            color: #ffd700 !important;  /* 使用金黃色以增加可讀性 */
            border: 1px solid #ffd700 !important;  /* 添加金黃色邊框 */
            text-shadow: 1px 1px 1px rgba(0,0,0,0.5);  /* 添加文字陰影 */
        }
        
        .chatbot {
            background-color: #2d2d2d;
            border-color: #4d4d4d;
        }
        
        .input-container {
            background-color: #2d2d2d;
            border-color: #4d4d4d;
        }
    }
    
    /* 標題樣式 */
    .header { 
        text-align: center;
        margin-bottom: 30px;
        padding: 20px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        color: white;
    }
    
    /* 聊天容器 */
    .chat-container { 
        height: 500px;
        overflow-y: auto;
        padding: 20px;
        background: white;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
    }
    
    /* 輸入區域 */
    .input-container { 
        margin-top: 20px;
        padding: 15px;
        background: white;
        border-radius: 10px;
    }
    
    /* 按鈕容器 */
    .button-container { 
        display: flex;
        gap: 10px;
        margin-top: 10px;
    }
    
    /* 按鈕樣式 */
    .button-primary {
        background: #4CAF50 !important;
        border: none !important;
        color: white !important;
    }
    
    .button-secondary {
        background: #f44336 !important;
        border: none !important;
        color: white !important;
    }
    
    /* Logo 樣式 */
    #logo img { 
        max-width: 150px;
        border-radius: 10px;
        box-shadow: none;
        border: none;
    }
    
    /* 免責聲明 */
    .disclaimer { 
        font-size: 0.9em;
        color: #666;
        margin-top: 15px;
        padding: 10px;
        background: #fff3cd;
        border-left: 4px solid #ffc107;
        border-radius: 4px;
    }

    /* QR Code 容器樣式 */
    .qr-code-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 10px;
        margin-top: 20px;
    }

    .qr-code-image {
        width: 200px;
        height: 200px;
        object-fit: contain;
    }

    .qr-code-label {
        text-align: center;
        font-size: 0.9em;
        color: #666;
        margin-top: 5px;
    }

    /* 載入狀態指示器 */
    .loading-spinner {
        display: none;
        margin: 10px auto;
        text-align: center;
    }
    
    .loading-spinner.active {
        display: block;
    }
    
    /* 移動端優化 */
    @media (max-width: 768px) {
        .chat-container {
            height: 60vh !important;
        }
        
        .input-container {
            margin-top: 10px;
            padding: 10px;
        }
        
        .button-container {
            flex-direction: column;
        }
        
        .qr-code-image {
            width: 150px;
            height: 150px;
        }
    }
    
    /* 錯誤提示動畫 */
    @keyframes shake {
        0%, 100% { transform: translateX(0); }
        25% { transform: translateX(-5px); }
        75% { transform: translateX(5px); }
    }
    
    .error-shake {
        animation: shake 0.5s ease-in-out;
    }
    """
) as demo:
    with gr.Row(elem_classes="header"):
        with gr.Column(scale=1):
            logo = gr.Image("GRC.png", elem_id="logo", width=150, show_label=False)
        with gr.Column(scale=6):
            gr.Markdown("# **智慧照顧產品推薦系統**")
        with gr.Column(scale=2, elem_classes="disclaimer"):
            gr.Markdown("""
            **免責聲明**：本系統應用ChatGPT進行智慧照顧產品推薦，
            提供之產品資訊僅供參考，使用者應自行前往各產品的官方網頁確認詳細資訊及最新規格。
            """)
    
    state = gr.State({"step": 0, "dialog_history": []})

    with gr.Row():
        with gr.Column(scale=12, elem_classes="chat-container"):
            loading_indicator = gr.HTML(
                '<div class="loading-spinner">處理中...</div>',
                visible=False
            )
            chatbot = gr.Chatbot(height=450, elem_classes="chatbot", show_label=False)
        with gr.Column(scale=4, elem_classes="input-container"):
            user_input = gr.Textbox(
                placeholder="請輸入您的需求...",
                show_label=False,
                interactive=True,
                lines=1
            )
            email = gr.Textbox(
                label="電子郵件",
                placeholder="請輸入您的電子郵件信箱",
                elem_classes="email-input"
            )
            with gr.Row(elem_classes="button-container"):
                send_email_btn = gr.Button("寄送郵件", variant="primary", elem_classes="button-primary")
                clear_chat_btn = gr.Button("清除聊天", variant="secondary", elem_classes="button-secondary")
            qr_code = gr.Image(
                "QRCode.png",
                show_label=False,  # 移除原本的標籤
                elem_id="qr_code",
                elem_classes="qr-code-image",
                width=200
            )
            gr.Markdown(
                "**掃描此QR Code填寫回饋表單**",
                elem_classes="qr-code-label"
            )
    
    async def process_input(user_input, state, email):
        loading_indicator.visible = True
        chat_history, state = query_chatgpt(user_input, state, email)
        loading_indicator.visible = False
        return chat_history, state, ""

    def handle_send_email(email, state):
        if not email:
            return [("Assistant", "請輸入有效的電子郵件地址")]
        
        if "email_content" not in state:
            return [("Assistant", "無法獲取推薦內容，請先進行推薦。")]
        
        subject = "智慧照顧產品推薦結果"
        result = send_email(email, subject, state["email_content"])
        return [("Assistant", result)]

    def clear_chat(state):
        global conversation
        conversation = []
        state = {"step": 0, "dialog_history": [], "current_category": None}
        return "", state

    user_input.submit(
        process_input,
        inputs=[user_input, state, email],
        outputs=[chatbot, state, user_input]
    )
    
    send_email_btn.click(
        fn=handle_send_email,
        inputs=[email, state],
        outputs=[chatbot]
    )
    
    clear_chat_btn.click(
        fn=clear_chat,
        inputs=[state],
        outputs=[chatbot, state]
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", 7860)),
        share=True
    )
