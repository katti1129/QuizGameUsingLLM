# AWS Lambda Pythonランタイムの公式ベースイメージを使用
FROM public.ecr.aws/lambda/python:3.11

# 作業ディレクトリをLambdaの実行環境に合わせて設定
WORKDIR ${LAMBDA_TASK_ROOT}

# requirements.txtをコピーし、依存関係をインストール
# まずrequirements.txtだけをコピーすることで、コード変更時のビルドキャッシュが効率化されます
COPY requirements.txt .
RUN pip install -r requirements.txt

# アプリケーションのコード全体をコピーします
COPY WebAPIboto3.py .

# --- ★★★ ここが最重要修正ポイント ★★★ ---
# Lambdaハンドラとして、Flaskの「app」オブジェクトを指定します。
# これにより、Lambdaのベースイメージに含まれるRIC (Runtime Interface Client)が
# aws_wsgiを介してFlaskアプリケーションを起動してくれます。
#
# 前提：WebAPIboto3.py ファイルの中で、Flaskアプリが app = Flask(__name__) のように
# 「app」という名前で定義されている必要があります。
CMD [ "WebAPIboto3.handler" ]