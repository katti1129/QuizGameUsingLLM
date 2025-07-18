import os
import time
import json
import random
from datetime import date
import google.generativeai as genai
from flask import Flask, jsonify
from dotenv import load_dotenv
from flask_cors import CORS

# --- AWS SDK (boto3) のインポート ---
import boto3


# --- 初期設定：道具や設計図を読み込む ---
# .envファイルからの読み込みは開発環境でテストする際のみ有効
# デプロイ環境（AWS Lambdaなど）ではLambdaの環境変数を使用するため、この行は実質的な影響なし
load_dotenv()
app = Flask(__name__)  # Flaskという基本設計でアプリを作る
CORS(app)  # 他の場所からの注文を許可する

# --- AWS Systems Manager Parameter Storeの設定 ---
SSM_CLIENT = boto3.client('ssm', region_name='ap-southeast-2')  # Systems Managerのクライアントを初期化

# Parameter Storeに保存したGoogle AI Studio APIキーの「名前（パス）」を指定
# これはLambdaの環境変数で設定することも可能です（推奨）。
# 例: /UnityGame/dev/auth/google_ai_studio_key
GOOGLE_AI_STUDIO_KEY_PARAM_NAME = os.environ.get(
    "GOOGLE_AI_STUDIO_KEY_PARAM_NAME",
    "/UnityGame/dev/auth/google_ai_studio_key"  # デフォルト値として指定
)

# Google AI Studio APIキーを保持するグローバル変数
GOOGLE_AI_STUDIO_API_KEY = None


# --- アプリケーション起動前にAPIキーを取得し、AIモデルを設定する ---
#@app.before_first_request
def setup_ai_model():
    global GOOGLE_AI_STUDIO_API_KEY  # グローバル変数を修正することを宣言
    print(">>> [システム] Parameter StoreからGoogle AI Studio APIキーを取得中...")
    try:
        # Parameter StoreからAPIキーを取得
        # SecureStringなのでWithDecryption=Trueが必要
        response = SSM_CLIENT.get_parameter(
            Name=GOOGLE_AI_STUDIO_KEY_PARAM_NAME,
            WithDecryption=True
        )

        print(response)

        GOOGLE_AI_STUDIO_API_KEY = response['Parameter']['Value']
        print(GOOGLE_AI_STUDIO_API_KEY)

        # --- Gemini APIのセットアップ ---
        genai.configure(api_key=GOOGLE_AI_STUDIO_API_KEY)
        # モデルのロード
        global model  # model変数もグローバルとして定義 (あるいはsetup_ai_model内で完結させる)
        model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
        print(">>> [システム] Google AIモデルのロードに成功しました。")

    except Exception as e:
        print(f"!!!!!! 重大なエラー !!!!!!")
        print(f"APIの初期設定に失敗しました。Parameter Storeからのキー取得またはAIモデル設定でエラー。")
        print(f"エラー内容: {e}")
        print(
            f"1. Lambda実行ロールにParameter Store (ssm:GetParameter) とKMS (kms:Decrypt) の権限があるか確認してください。")
        print(f"2. Parameter Storeのパラメータ名 ({GOOGLE_AI_STUDIO_KEY_PARAM_NAME}) が正しいか確認してください。")
        print(f"3. Parameter StoreにAPIキーがSecureStringで正しく保存されているか確認してください。")
        exit()  # サーバーを停止 (Lambdaでは関数の実行が終了する)


# --- ビュッフェとコース料理、そしてルールの設定 ---
# レートリミット設定
MINUTE_LIMIT = 55
MINUTE_WINDOW = 60
request_timestamps = []

# API呼び出し上限設定
DAILY_API_LIMIT = 500
api_call_count = 0
last_reset_date = date.today()

# キャッシュとセットの設定
QUIZ_CACHE = []
SERVING_POOL = []
SET_SIZE = 5


# --- 「/quiz」という注文が来た時の対応マニュアル ---
@app.route('/quiz', methods=['GET'])
def generate_quiz():
    global QUIZ_CACHE, SERVING_POOL, api_call_count, last_reset_date, request_timestamps

    # モデルがロードされているか確認
    if GOOGLE_AI_STUDIO_API_KEY is None:
        print("!!!!!! エラー !!!!!! Google AI Studio API Keyがロードされていません。")
        return jsonify({"error": "Backend not fully initialized. API key missing."}), 500
    # ここで model も None ではないことを確認するロジックを追加しても良い

    # --- ルール1：1分あたりのリクエスト数制限チェック ---
    current_time = time.time()
    request_timestamps = [t for t in request_timestamps if current_time - t < MINUTE_WINDOW]
    if len(request_timestamps) >= MINUTE_LIMIT:
        print(f">>> [レートリミット] 1分あたりのリクエスト上限({MINUTE_LIMIT}回)に達しました。")
        return jsonify({"error": f"Rate limit of {MINUTE_LIMIT} requests per minute exceeded."}), 429
    request_timestamps.append(current_time)

    # --- コース料理とビュッフェのロジック ---
    if SERVING_POOL:
        print(f">>> [コース提供] 配膳トレイから提供します。(残り {len(SERVING_POOL) - 1} 品)")
        quiz = SERVING_POOL.pop()
        return jsonify(quiz)

    print("--- 配膳トレイが空です。次の準備をします。 ---")

    today = date.today()
    if today > last_reset_date:
        api_call_count = 0
        last_reset_date = today
        print(f">>> [システム] 新しい日です。API発注回数をリセットしました。")

    if len(QUIZ_CACHE) < SET_SIZE and api_call_count < DAILY_API_LIMIT:
        print(f">>> [ビュッフェ補充] 品数不足のため、新しいクイズを調理します。")
        try:
            api_call_count += 1
            print(f">>> [システム] AIを発注します。(本日 {api_call_count}/{DAILY_API_LIMIT} 回目)")

            prompt = """
                        日本の歴史に関する面白い二択クイズを1問、JSON形式で生成してください。
                        以下のフォーマット厳守で、各選択肢の根拠も追加してください。

                        {
                          "question": "問題文",
                          "options": ["選択肢A", "選択肢B"],
                          "answer": "正解の選択肢 (例: 選択肢A または 選択肢B)",
                          "explanation_A": "選択肢Aに関する簡潔な説明や、それが正解または不正解である根拠。",
                          "explanation_B": "選択肢Bに関する簡潔な説明や、それが正解または不正解である根拠。"
                        }
                        """
            response = model.start_chat(history=[]).send_message(prompt)  # modelは既にsetup_ai_modelで設定済み
            #print(response.text)

            #raw_text = response.text.decode('utf-16-be').encode('utf-8')
            raw_text = response.text


            json_start = raw_text.find('{')
            json_end = raw_text.rfind('}') + 1

            if json_start != -1 and json_end != 0:
                json_string = raw_text[json_start:json_end]
                new_quiz = json.loads(json_string)
            else:
                raise ValueError("AIの応答から有効なJSONを見つけられませんでした。")

            QUIZ_CACHE.append(new_quiz)
            print(f">>> [システム] ビュッフェ台に1品追加しました。(現在 {len(QUIZ_CACHE)}品)")
            return jsonify(new_quiz)

        except Exception as e:
            print(
                f"!!!!!! エラー発生 !!!!!!\nエラー内容: {e}\nAIからの生の応答: {response.text if 'response' in locals() else 'N/A'}")
            return jsonify({"error": str(e)}), 500
    else:
        if not QUIZ_CACHE:
            return jsonify({"error": "Daily API limit reached and no quizzes are available."}), 429

        print(f">>> [コース準備] ビュッフェ台から新しいコースを用意します。")
        SERVING_POOL = QUIZ_CACHE.copy()
        random.shuffle(SERVING_POOL)

        quiz = SERVING_POOL.pop()
        print(f">>> [コース提供] 新しいコースの1品目を提供します。")
        return jsonify(quiz)


# デバッグモードで開発用サーバーを起動
if __name__ == '__main__':
    # ローカルでテストする場合、Parameter Storeのキーを読み取るにはAWS認証情報が必要です
    # 例: ~/.aws/credentials ファイルの設定や、環境変数 AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY など
    setup_ai_model()
    app.run(host='0.0.0.0', port=5000, debug=True)

# ... (Flaskアプリケーションのコード全体) ...

# --- Lambdaのハンドラ関数 (AWS WSGIを使用) ---
from aws_wsgi import handle_request  # これが重要


def lambda_handler(event, context):
    return handle_request(app, event, context)  # これが重要