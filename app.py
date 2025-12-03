import os
import random
import string
import time
import threading
import zipfile
import io
from flask import Flask, request, render_template, url_for, jsonify, send_file
from PIL import Image

# --- 配置 ---
UPLOAD_FOLDER = 'static/uploaded_images'
# 允许的图片扩展名，用于上传时校验
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'} 
PORT = 5555
CLEANUP_INTERVAL_HOURS = 1 # 后台清理任务每隔1小时运行一次
FILE_EXPIRY_SECONDS = 24 * 60 * 60 # 24小时 = 86400秒

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# 确保上传文件夹存在
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# --- 辅助函数 ---

def allowed_file(filename):
    """检查文件扩展名是否在允许的列表中"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_random_id(length=8):
    """生成一个指定长度的随机数字字母字符串作为ID"""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

# --- 后台清理任务 ---

def cleanup_files():
    """在后台线程中运行，删除超过 24 小时的 ZIP 文件"""
    while True:
        # 计算过期时间戳 (当前时间 - 24小时)
        cutoff_time = time.time() - FILE_EXPIRY_SECONDS 
        
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] 启动文件清理任务...")

        try:
            for filename in os.listdir(UPLOAD_FOLDER):
                if filename.endswith('.zip'):
                    filepath = os.path.join(UPLOAD_FOLDER, filename)
                    # 获取文件的修改时间 (ctime 或 mtime 都可以，mtime更常用)
                    file_mtime = os.path.getmtime(filepath) 
                    
                    if file_mtime < cutoff_time:
                        print(f"正在删除过期文件: {filename}")
                        os.remove(filepath)
        except Exception as e:
            print(f"清理过程中发生错误: {e}")
            
        # 线程休眠指定的小时数
        time.sleep(CLEANUP_INTERVAL_HOURS * 60 * 60) 

# --- 路由定义 ---

@app.route('/')
def index():
    """主页：显示上传界面"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """处理文件上传请求，并将图片打包成 ZIP 存储"""
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # 1. 检查文件类型并准备命名
    if file and allowed_file(file.filename):
        # 原始图片扩展名
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        
        # 8位随机ID
        random_id = generate_random_id(8)
        # 存储的文件名为 ID.zip
        zip_filename = f"{random_id}.zip"
        zip_filepath = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
        
        # 压缩包内部的文件名，使用 ID 和原始扩展名
        filename_inside_zip = f"{random_id}.{file_ext}"

        try:
            # 2. 读取文件内容到内存并进行图片有效性校验
            # 使用 file.stream.read() 会读取整个文件内容，但 file.stream 是一个临时的文件句柄，
            # 需要在读取后重置位置或使用 file.read()，但 file.read() 只能调用一次。
            # 最佳实践是先读取到内存流，然后使用 PIL 校验。
            file_stream = io.BytesIO(file.read())
            Image.open(file_stream) # 如果不是有效图片，会抛出异常
            
            # 3. 创建 ZIP 文件
            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zf:
                file_stream.seek(0) # 重置内存流的指针到开头
                # 将图片数据写入 ZIP 文件，并指定内部文件名
                zf.writestr(filename_inside_zip, file_stream.read())
            
            # 4. 生成图片访问链接
            file_url = url_for('view_image', random_id=random_id, _external=True)
            
            return jsonify({
                'success': True,
                'filename': zip_filename,
                'url': file_url
            }), 200
        except Exception as e:
            # 捕获图片校验失败或写入错误
            return jsonify({'error': f'无效的图片文件或服务器错误: {e}'}), 400

    return jsonify({'error': '文件类型不被允许'}), 400

@app.route('/view_image/<random_id>')
def view_image(random_id):
    """根据随机 ID，从 ZIP 存档中读取并显示图片"""
    zip_filename = f"{random_id}.zip"
    zip_filepath = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)

    if not os.path.exists(zip_filepath):
        return "图片文件未找到或已过期删除。", 404

    try:
        with zipfile.ZipFile(zip_filepath, 'r') as zf:
            # 假设 ZIP 中只包含一个图片文件，找到第一个文件
            file_list = zf.namelist()
            if not file_list:
                return "ZIP 存档为空。", 500
            
            image_in_zip = file_list[0]
            
            # 根据内部文件名获取扩展名，确定 MimeType
            file_ext = image_in_zip.rsplit('.', 1)[1].lower()
            mimetype = f'image/{file_ext}'
            if file_ext == 'jpg':
                mimetype = 'image/jpeg'
            
            # 读取图片数据到内存缓冲区
            image_data = zf.read(image_in_zip)
            buffer = io.BytesIO(image_data)
            
            # 使用 send_file 从内存缓冲区发送文件内容
            return send_file(
                buffer,
                mimetype=mimetype,
                as_attachment=False # 关键: 设置为 False 让浏览器直接显示图片
            )
            
    except zipfile.BadZipFile:
        return "无效的 ZIP 存档。", 500
    except Exception as e:
        return f"加载图片时发生错误: {e}", 500

if __name__ == '__main__':
    # 启动后台清理线程
    # use_reloader=False 避免在 debug 模式下线程启动两次
    cleanup_thread = threading.Thread(target=cleanup_files, daemon=True)
    cleanup_thread.start()
    
    # 启动 Flask 应用
    print(f"服务器已启动，访问地址: http://127.0.0.1:{PORT}")
    app.run(port=PORT, debug=True, threaded=True, use_reloader=False)