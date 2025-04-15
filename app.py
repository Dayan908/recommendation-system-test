import openai
import gradio as gr
import pandas as pd
import os
import smtplib
import logging
import tiktoken
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
api_cost = 0.0
system_tokens = 0  # 系統提示的 tokens
excel_tokens = 0   # Excel 資料的 tokens
base_tokens = 0  # 用於存儲 system prompt 和 Excel 資料的 tokens
product_categories = {}  # 初始化產品分類字典
system_prompt_loaded = False  # 追蹤系統提示是否已加載

# 定義系統提示
base_system_prompt = """# 角色與目標
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
    for _, row in df.iterrows():
        category = row['產品第一層分類']
        if category not in product_categories:
            product_categories[category] = []
        product_categories[category].append(row.to_dict())
except Exception as e:
    logging.error(f"初始化數據時發生錯誤: {str(e)}")
    raise

def count_tokens(text):
    """使用 tiktoken 計算文本的 token 數量"""
    try:
        # 使用 o3-mini-2025-01-31 模型對應的編碼器
        encoding = tiktoken.get_encoding("cl100k_base")
        tokens = len(encoding.encode(text))
        return tokens
    except Exception as e:
        logging.error(f"計算 tokens 時發生錯誤: {str(e)}")
        return 0

def calculate_system_tokens():
    """計算系統提示的 tokens"""
    try:
        base_system_prompt = """# 角色與目標
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
        tokens = count_tokens(base_system_prompt)
        logging.info(f"系統提示 tokens 計算完成: {tokens}")
        return tokens
    except Exception as e:
        logging.error(f"計算系統提示 tokens 時發生錯誤: {str(e)}")
        return 0

def calculate_excel_tokens():
    """計算 Excel 資料的 tokens"""
    try:
        excel_text = ""
        for category, products in product_categories.items():
            for product in products:
                product_text = (
                    f"產品名稱：{product.get('產品名稱', 'N/A')}\n"
                    f"公司名稱：{product.get('公司名稱', 'N/A')}\n"
                    f"主要功能：{product.get('主要功能', 'N/A')}\n"
                    f"使用方式：{product.get('使用方式', 'N/A')}\n"
                    f"產品網址：{product.get('產品網址', 'N/A')}\n"
                    f"連絡電話：{product.get('連絡電話', 'N/A')}\n"
                    f"分類：{product.get('產品第一層分類', 'N/A')} > {product.get('產品第二層分類', 'N/A')}\n"
                )
                excel_text += product_text
        
        tokens = count_tokens(excel_text)
        logging.info(f"Excel 資料 tokens 計算完成: {tokens}")
        return tokens
    except Exception as e:
        logging.error(f"計算 Excel 資料 tokens 時發生錯誤: {str(e)}")
        return 0

# 計算初始 tokens
system_tokens = calculate_system_tokens()
excel_tokens = calculate_excel_tokens()
logging.info(f"初始化完成 - 系統提示 tokens: {system_tokens}, Excel 資料 tokens: {excel_tokens}")

def get_category_products(category):
    """獲取特定分類的產品數據"""
    if category in product_categories:
        return product_categories[category]
    return []

def calculate_base_tokens():
    """計算系統提示和 Excel 資料的 tokens"""
    global base_tokens
    try:
        # 計算 system prompt 的 tokens
        base_system_prompt = """# 角色與目標
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
        system_tokens = calculate_system_tokens()
        
        # 計算 Excel 資料的 tokens
        excel_text = ""
        for category, products in product_categories.items():
            for product in products:
                product_text = (
                    f"產品名稱：{product.get('產品名稱', 'N/A')}\n"
                    f"公司名稱：{product.get('公司名稱', 'N/A')}\n"
                    f"主要功能：{product.get('主要功能', 'N/A')}\n"
                    f"使用方式：{product.get('使用方式', 'N/A')}\n"
                    f"產品網址：{product.get('產品網址', 'N/A')}\n"
                    f"連絡電話：{product.get('連絡電話', 'N/A')}\n"
                    f"分類：{product.get('產品第一層分類', 'N/A')} > {product.get('產品第二層分類', 'N/A')}\n"
                )
                excel_text += product_text
        
        excel_tokens = calculate_excel_tokens()
        
        # 總基礎 tokens
        base_tokens = system_tokens + excel_tokens
        logging.info(f"基礎 tokens 計算完成 - 系統提示: {system_tokens}, Excel 資料: {excel_tokens}")
        
    except Exception as e:
        logging.error(f"計算基礎 tokens 時發生錯誤: {str(e)}")
        base_tokens = 0

# 在初始化時計算基礎 tokens
try:
    calculate_base_tokens()
except Exception as e:
    logging.error(f"初始化基礎 tokens 時發生錯誤: {str(e)}")

def calculate_api_cost(response, is_new_conversation=False):
    """計算 API 使用成本"""
    global api_cost
    try:
        # 獲取輸入和輸出的 token 數量
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        
        # 記錄詳細的 tokens 信息
        if is_new_conversation:
            logging.info(f"新對話 tokens 明細:")
            logging.info(f"- 系統提示+產品資料 tokens: {prompt_tokens}")
            logging.info(f"- 總輸入 tokens: {prompt_tokens}")
        else:
            logging.info(f"持續對話 tokens 明細:")
            logging.info(f"- 輸入 tokens: {prompt_tokens}")
        
        # o3-mini-2025-01-31 的定價
        input_cost_per_1k = 0.0005  # 每 1000 個輸入 token 的價格
        output_cost_per_1k = 0.0015  # 每 1000 個輸出 token 的價格
        
        # 計算本次請求的成本
        input_cost = (prompt_tokens / 1000) * input_cost_per_1k
        output_cost = (completion_tokens / 1000) * output_cost_per_1k
        total_cost = input_cost + output_cost
        
        # 更新總成本
        api_cost += total_cost
        
        # 記錄詳細的成本信息
        logging.info(f"API 成本計算 - 輸入tokens: {prompt_tokens}, 輸出tokens: {completion_tokens}")
        logging.info(f"成本明細 - 輸入成本: ${input_cost:.6f}, 輸出成本: ${output_cost:.6f}, 總成本: ${total_cost:.6f}")
        logging.info(f"單價 - 輸入: ${input_cost_per_1k}/1K tokens, 輸出: ${output_cost_per_1k}/1K tokens")
        logging.info(f"累計總成本: ${api_cost:.6f}")
        
        return total_cost, api_cost
    except Exception as e:
        logging.error(f"計算 API 成本時發生錯誤: {str(e)}")
        return 0.0, api_cost

def query_chatgpt(user_input, state, email):
    global conversation, current_step, api_cost, system_prompt_loaded
    
    # 將debug信息添加到日誌
    logging.info(f"查詢前狀態 - system_prompt_loaded: {system_prompt_loaded}, 對話長度: {len(conversation)}")
    
    # 判斷是否是新對話
    is_new_conversation = (
        "你好" in user_input or 
        "開始" in user_input or 
        "重新" in user_input or
        len(conversation) == 0
    )
    
    try:
        # 如果是新對話，清空對話歷史和系統提示狀態
        if is_new_conversation:
            conversation = []
            system_prompt_loaded = False
            logging.info(f"開始新對話 - 基礎 tokens: 系統提示({system_tokens}) + Excel資料({excel_tokens}) = {system_tokens + excel_tokens}")
            logging.info(f"重置系統提示狀態: system_prompt_loaded = {system_prompt_loaded}")
        
        # 限制對話歷史長度，只保留最近的 10 輪對話
        if len(conversation) > 20:  # 每輪對話包含 user 和 assistant 各一條消息
            # 保留系統提示消息，只清理用戶和助手的對話
            system_message = conversation[0] if conversation and conversation[0]["role"] == "system" else None
            conversation = conversation[-20:]
            # 如果原本有系統提示但被清理掉了，重新添加
            if system_message and (not conversation or conversation[0]["role"] != "system"):
                conversation.insert(0, system_message)
                # 確保系統提示標記保持為真
                system_prompt_loaded = True
                logging.info("對話歷史截斷，已保留系統提示")
        
        # 只在系統提示未加載時加載
        if not system_prompt_loaded:
            logging.info("需要加載系統提示")
            relevant_products = []
            if "current_category" in state and state["current_category"]:
                products = product_categories.get(state["current_category"], [])
                relevant_products.extend(products)
            else:
                for category, products in product_categories.items():
                    relevant_products.extend(products)
    
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
            
            # 將系統提示添加為第一條消息，確保清除之前的對話歷史
            if len(conversation) > 0 and conversation[0]["role"] == "system":
                # 如果已有system消息，替換它
                conversation[0] = {"role": "system", "content": system_prompt}
            else:
                # 否則添加新的system消息
                conversation.insert(0, {"role": "system", "content": system_prompt})
            
            system_prompt_loaded = True
            logging.info("已添加系統提示和產品資訊到對話歷史中")
            logging.info(f"系統提示狀態更新: system_prompt_loaded = {system_prompt_loaded}")
        else:
            logging.info("系統提示已加載，無需重新加載")

        # 添加用戶消息到對話歷史
        conversation.append({"role": "user", "content": user_input})

        # 建立消息結構 - 使用整個對話歷史而不是每次都重新添加系統提示
        # 創建一個副本以避免修改原始對話歷史
        messages_to_send = conversation.copy()
        
        # 確保messages_to_send中system消息只在第一位置
        if len(messages_to_send) > 0 and messages_to_send[0]["role"] == "system":
            # 記錄發送的對話長度和第一條消息類型
            logging.info(f"發送請求 - 對話歷史長度: {len(messages_to_send)}, 第一條消息類型: {messages_to_send[0]['role']}")
            logging.info(f"前10個字符: {messages_to_send[0]['content'][:10]}...")
        else:
            logging.warning("警告: 發送請求中沒有系統提示消息")
            
        response = openai.ChatCompletion.create(
            model="o3-mini-2025-01-31",
            messages=messages_to_send
        )

        # 計算本次請求的成本
        current_cost, total_cost = calculate_api_cost(response, is_new_conversation)
        
        reply = response.choices[0].message.content
        conversation.append({"role": "assistant", "content": reply})

        # 添加成本信息到回覆中
        cost_info = f"\n\n[本次請求成本: ${current_cost:.4f} | 累計成本: ${total_cost:.4f}]"
        reply += cost_info

        # 更新當前分類（如果在回覆中提到）
        for category in product_categories.keys():
            if category in reply:
                state["current_category"] = category
                break

        state["recommendations"] = reply
        state["email_content"] = reply

        # 創建對話歷史 - 跳過第一條系統消息
        conversation_history = []
        for i in range(1, len(conversation) - 1, 2):
            if i+1 < len(conversation):
                conversation_history.append((conversation[i]['content'], conversation[i+1]['content']))

        logging.info("成功生成推薦回應")
        logging.info(f"查詢後狀態 - system_prompt_loaded: {system_prompt_loaded}, 對話長度: {len(conversation)}")
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
    # 此函數不再需要修改，直接使用原有的 query_chatgpt
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
        
        .chat-display-container,
        .chat-input-container,
        .sidebar-container {
            background-color: #2d2d2d !important;
            border-color: #4d4d4d !important;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2) !important;
        }
        
        .main-input textarea {
            background-color: #3d3d3d !important;
            color: #e0e0e0 !important;
            border-color: #4d4d4d !important;
        }
        
        .main-input:focus-within {
            border-color: #6d7cde !important;
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
    .chat-display-container {
        display: flex;
        flex-direction: column;
        height: 460px;
        margin-bottom: 5px;
        background: white;
        border-radius: 10px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        overflow: hidden;
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
        margin-bottom: 15px;
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
        padding: 10px;
        background: rgba(0, 0, 0, 0.05);
        border-radius: 8px;
        font-size: 14px;
        color: #555;
    }
    
    .loading-spinner.active {
        display: block;
    }

    /* 聊天消息加載中樣式 */
    .chatbot .message.typing::after {
        content: "";
        display: inline-block;
        width: 8px;
        height: 8px;
        background-color: #888;
        border-radius: 50%;
        margin-left: 3px;
        animation: typing-dot 1s infinite;
    }

    @keyframes typing-dot {
        0%, 100% { opacity: 0.2; }
        50% { opacity: 1; }
    }
    
    /* 移動端優化 */
    @media (max-width: 768px) {
        .chat-display-container {
            height: 60vh !important;
        }
        
        .sidebar-container {
            margin-left: 0;
            margin-top: 15px;
        }
        
        .button-container {
            flex-direction: column;
        }
        
        .qr-code-image {
            width: 150px;
            height: 150px;
        }
        
        .main-input textarea {
            padding: 10px !important;
            min-height: 50px !important;
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

    /* 輸入容器樣式 */
    .chat-input-container {
        background: white;
        border-radius: 10px;
        padding: 10px 15px;
        margin-top: 5px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        display: flex;
        align-items: center;
        width: 100%;  /* 確保容器佔滿整行 */
    }
    
    /* 主輸入欄樣式 */
    .main-input {
        margin: 10px 0 !important;
        border: 1px solid #ddd !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05) !important;
        transition: border-color 0.3s, box-shadow 0.3s !important;
        flex-grow: 1 !important;  /* 讓輸入框佔據所有可用空間 */
    }
    
    .main-input:focus-within {
        border-color: #667eea !important;
        box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.25) !important;
    }
    
    .main-input textarea {
        padding: 12px 15px !important;
        font-size: 1.05em !important;
        min-height: 44px !important;
        line-height: 20px !important;
    }
    
    /* 提交按鈕樣式 */
    .main-input button[type="submit"] {
        background: #4CAF50 !important;
        border: none !important;
        color: white !important;
        padding: 8px 15px !important;
        border-radius: 4px !important;
        cursor: pointer !important;
        transition: background 0.3s !important;
        margin-left: 8px !important;
        height: 36px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }
    
    .main-input button[type="submit"]:hover {
        background: #45a049 !important;
    }
    
    /* 深色模式下的提交按鈕 */
    @media (prefers-color-scheme: dark) {
        .main-input button[type="submit"] {
            background: #5d8b60 !important;
        }
        .main-input button[type="submit"]:hover {
            background: #4a7a4c !important;
        }
    }
    
    /* 側邊欄容器 */
    .sidebar-container {
        background: white;
        border-radius: 10px;
        padding: 15px;
        margin-left: 15px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.05);
        height: fit-content;
    }

    /* 成本顯示區域樣式 */
    .cost-display {
        background: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        margin: 10px 0;
        text-align: right;
        font-size: 0.9em;
        color: #666;
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
        # 主要聊天區域
        with gr.Column(scale=12):
            # 聊天顯示區域
            with gr.Box(elem_classes="chat-display-container"):
                loading_indicator = gr.HTML(
                    '<div class="loading-spinner">ChatGPT 正在思考回應中...</div>',
                    visible=False
                )
                chatbot = gr.Chatbot(height=400, elem_classes="chatbot", show_label=False)
            
            # 輸入區域（類似 LINE 的底部輸入框）
            with gr.Box(elem_classes="chat-input-container"):
                with gr.Row():
                    user_input = gr.Textbox(
                        placeholder="請輸入您的需求...",
                        show_label=False,
                        interactive=True,
                        lines=1,  # 單行模式
                        elem_classes="main-input",
                        scale=1  # 使其佔據整行
                    )
        
        # 側邊欄區域（郵件、按鈕和 QR 碼）
        with gr.Column(scale=4, elem_classes="sidebar-container"):
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
                show_label=False,
                elem_id="qr_code",
                elem_classes="qr-code-image",
                width=200
            )
            gr.Markdown(
                "**掃描此QR Code填寫回饋表單**",
                elem_classes="qr-code-label"
            )
    
    # 添加成本顯示區域
    with gr.Row():
        cost_display = gr.Markdown(
            "預估API成本: $0.0000",
            elem_classes="cost-display"
        )
    
    # 修改處理輸入的函數，使用戶訊息立即顯示
    def process_input(user_input, chatbot, state, email):
        if not user_input.strip():
            return chatbot, state, "", ""  # 修改返回值，清空輸入框
        
        # 先將用戶訊息添加到聊天視窗
        chatbot = chatbot + [(user_input, None)]
        
        # 返回更新後的界面，使用戶訊息立即顯示，並清空輸入框
        return chatbot, state, "", user_input
        
    # 添加一個新函數來處理 API 響應
    def process_response(chatbot, state, last_user_input, email):
        if not chatbot or not last_user_input:
            return chatbot, state, "", f"預估API成本: $0.0000"
            
        loading_indicator.visible = True
        
        try:
            chat_history, updated_state = query_chatgpt(last_user_input, state, email)
            
            # 更新成本顯示
            cost_display_text = f"預估API成本: ${api_cost:.4f}"
            
            # 從 chat_history 中獲取 AI 回應
            ai_response = "無法獲取回應"
            if isinstance(chat_history, list) and len(chat_history) > 0:
                latest_response = chat_history[-1]
                if isinstance(latest_response, tuple) and len(latest_response) > 1:
                    ai_response = latest_response[1]
            
            # 更新聊天窗口中最後一條消息的回應部分
            if len(chatbot) > 0:
                chatbot[-1] = (chatbot[-1][0], ai_response)
            
        except Exception as e:
            logging.error(f"處理回應時發生錯誤: {str(e)}")
            if len(chatbot) > 0:
                chatbot[-1] = (chatbot[-1][0], "抱歉，處理您的請求時發生錯誤，請重試。")
            cost_display_text = f"預估API成本: ${api_cost:.4f}"
        
        loading_indicator.visible = False
        
        # 返回更新後的界面並清空輸入框
        return chatbot, updated_state, "", cost_display_text
    
    # 修改事件處理，添加成本顯示的更新
    user_input.submit(
        fn=process_input,
        inputs=[user_input, chatbot, state, email],
        outputs=[chatbot, state, user_input, user_input]
    ).then(
        fn=process_response,
        inputs=[chatbot, state, user_input, email],
        outputs=[chatbot, state, user_input, cost_display]
    )

    def handle_send_email(email, state):
        if not email:
            return [("Assistant", "請輸入有效的電子郵件地址")]
        
        if "email_content" not in state:
            return [("Assistant", "無法獲取推薦內容，請先進行推薦。")]
        
        subject = "智慧照顧產品推薦結果"
        result = send_email(email, subject, state["email_content"])
        return [("Assistant", result)]

    def clear_chat(state):
        global conversation, api_cost, system_prompt_loaded
        conversation = []
        system_prompt_loaded = False  # 重置系統提示加載狀態
        state = {
            "step": 0,
            "top_matches": None,
            "products_info": None,
            "recommendations": "",
            "email_content": "",
            "chat_history": [],
            "current_category": None
        }
        # 不重置 api_cost，因為我們要保留總計費用
        return [], state, ""  # 返回空的聊天記錄、重置的狀態和空的輸入框
    
    send_email_btn.click(
        fn=handle_send_email,
        inputs=[email, state],
        outputs=[chatbot]
    )
    
    clear_chat_btn.click(
        fn=clear_chat,
        inputs=[state],
        outputs=[chatbot, state, user_input]
    )

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=int(os.getenv("PORT", 7860)),
        share=True
    )
