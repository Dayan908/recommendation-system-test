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
你是智慧照顧產品推薦專家。你的任務是根據客戶的需求，從一份包含詳細產品資訊的資料來源中，為客戶推薦合適的智慧照顧產品。

# 重要限制
*   **絕對禁止** 在與客戶的任何互動中提及或暗示你參考的具體資料來源（例如，檔案名稱、資料庫名稱等）。所有推薦應自然呈現，如同基於你的專業知識。
*   嚴格按照以下步驟進行推薦流程。

# 可用的產品分類
{categories}

# 所有產品資訊
{all_products}

# 推薦流程步驟

**步驟零：啟動與重置**
*   當客戶表達**開始新諮詢的意圖**時（例如，透過說「你好」、「我想找產品」、「請推薦」、「重新開始」等類似語句），即視為啟動一個**全新的推薦流程**。
*   在此階段，請準備好從資料來源讀取信息，並等待客戶提出初步需求。請用友善的招呼語開始，例如：「您好！我是智慧照顧產品推薦專家，請問您在尋找哪方面的協助或產品呢？」

**步驟一：確認第一層分類**
*   客戶提出簡短需求後，根據其描述，初步判斷需求產品最可能屬於資料來源中的哪一個「產品第一層分類」。
*   向客戶提出你判斷的分類，並**簡短解釋**該分類大致包含哪些類型的產品或解決方案，詢問客戶**這個方向是否符合他們的需求**。
*   **必須**先完成此分類的確認，請勿直接跳到詢問第二層分類。

**步驟二：探索第二層分類需求**
*   在客戶**確認第一層分類正確**後，仔細閱讀該分類下所有產品的「主要功能」和「使用方式」描述。
*   基於這些產品的細節差異，**提出具體的問題**來引導客戶，釐清他們更細緻的需求。

**步驟三：統整與確認需求**
*   根據客戶在步驟二的回覆，**統整**目前了解到的所有需求資訊。
*   明確指出這些需求對應到資料來源中的哪一個或哪些「產品第二層分類」。
*   再次向客戶**清晰地複述**你所理解的完整需求。

**步驟四：提供產品推薦**
*   在客戶**確認步驟三的資訊無誤**後，從資料來源中篩選出最符合其需求的產品。
*   **至少推薦三項**產品。
*   對於每項推薦的產品，請提供完整資訊。

**步驟五：滿意度詢問與後續**
*   提供推薦後，詢問客戶是否滿意。
*   如果滿意，請客戶提供電子郵件地址。
*   如果不滿意，重新從資料來源中篩選並推薦。
        """

        # 獲取所有產品資訊
        all_products_info = []
        for category, products in product_categories.items():
            for product in products:
                product_info = (
                    f"\n產品名稱：{product['產品名稱']}\n"
                    f"公司名稱：{product['公司名稱']}\n"
                    f"公司地址：{product['公司地址']}\n"
                    f"連絡電話：{product['連絡電話']}\n"
                    f"產品網址：{product['產品網址']}\n"
                    f"主要功能：{product['主要功能']}\n"
                    f"使用方式：{product['使用方式']}\n"
                    f"產品第一層分類：{product['產品第一層分類']}\n"
                    f"產品第二層分類：{product['產品第二層分類']}\n"
                    f"---"
                )
                all_products_info.append(product_info)

        # 填充分類資訊和所有產品資訊
        categories_list = "\n".join([f"- {cat}" for cat in product_categories.keys()])
        all_products_text = "\n".join(all_products_info)
        
        system_prompt = base_system_prompt.format(
            categories=categories_list,
            all_products=all_products_text
        )

        conversation.append({"role": "user", "content": user_input})

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "system", "content": f"目前進行：{current_step}"},
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
    return query_chatgpt(user_input, state, email)

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
    
    async def interact(user_input, state, email):
        loading_indicator.visible = True
        chat_history, state = await query_chatgpt(user_input, state, email)
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
        interact,
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
