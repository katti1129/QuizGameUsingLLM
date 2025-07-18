import os
import time
import json
import random
from datetime import date
import google.generativeai as genai
from flask import Flask, jsonify
from dotenv import load_dotenv
from flask_cors import CORS

# --- 初期設定：道具や設計図を読み込む ---
load_dotenv()  # .envファイルから秘伝のレシピを読み込む
app = Flask(__name__)  # Flaskという基本設計でアプリを作る
CORS(app)  # 他の場所からの注文を許可する

# --- Gemini APIのセットアップ ---
# このtry...exceptブロックの中に、お探しの行が含まれています。
try:
    # ★★★ お探しの行は、おそらくこちらになります ★★★
    api_key = os.environ.get("GOOGLE_API_KEY")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('models/gemini-1.5-flash-latest')
    print(">>> [システム] Google AIモデルのロードに成功しました。")
except Exception as e:
    # このエラーメッセージは、APIキーの設定自体で問題が起きた場合に表示されます
    print(f"!!!!!! 重大なエラー !!!!!!\nAPIの初期設定に失敗しました。エラー内容: {e}")
    print(
        "1. .envファイルが正しい場所にあるか、2. ファイル名が「.env」か、3. ファイルの中身が正しいか、を再確認してください。")
    exit()  # サーバーを停止

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

            prompt = "日本の歴史に関する面白い二択クイズを1問、JSON形式で{\"question\": \"問題文\", \"options\": [\"選択肢A\", \"選択肢B\"], \"answer\": \"正解の選択肢\"} の形式で生成してください。"
            response = model.start_chat(history=[]).send_message(prompt)
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
    app.run(host='0.0.0.0', port=5000, debug=True)