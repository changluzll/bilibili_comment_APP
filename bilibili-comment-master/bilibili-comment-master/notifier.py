# filename: notifier.py
import requests
import os

# 定义配置文件的名称
WEBHOOK_CONFIG_FILE = 'webhook_config.txt'


def check_webhook_configured():
    """检查 Webhook 配置文件是否存在且不为空。"""
    if not os.path.exists(WEBHOOK_CONFIG_FILE):
        return False
    try:
        with open(WEBHOOK_CONFIG_FILE, 'r', encoding='utf-8') as f:
            # 确保读取到的URL不只是空白字符
            return f.read().strip() != ""
    except Exception:
        return False


def send_webhook_notification(video_title, new_comments):
    """
    格式化新评论信息并将其发送到配置的 Webhook URL。
    支持简单的文本格式，兼容 Discord, Slack, 飞书, 钉钉等多种平台。
    """
    # 再次检查配置，这是一个安全措施
    if not check_webhook_configured():
        return

    with open(WEBHOOK_CONFIG_FILE, 'r', encoding='utf-8') as f:
        webhook_url = f.read().strip()

    # 格式化通知内容
    # 这种格式在大多数平台上都表现良好
    message_lines = [
        f"【B站评论监控】🔥 **【{video_title}】发现 {len(new_comments)} 条新评论！**",
        "--------------------------------------"
    ]
    for comment in new_comments:
        # 清理可能破坏JSON或Markdown的字符
        user = comment['user'].replace('`', '').replace('*', '')
        message = comment['message'].replace('`', '').replace('*', '')

        comment_block = (
            f"**用户:** {user}\n"
            f"**类型:** {comment['type']}\n"
            f"**内容:** {message}\n"
            f"**时间:** {comment['time'].strftime('%Y-%m-%d %H:%M:%S')}"
        )
        message_lines.append(comment_block)
        message_lines.append("--------------------------------------")

    full_message = "\n".join(message_lines)

    # 构建通用的 JSON payload
    # 2025年8月22日12:04:58 实测 钉钉 企业微信 OK
    payload = {
        "msgtype": "text",
        "text": {
            "content": full_message
            } 
        }

    # 发送POST请求
    try:
        response = requests.post(webhook_url, json=payload, timeout=10)
        # 检查响应状态码，如果是不成功的状态码（如4xx, 5xx），则会抛出异常
        response.raise_for_status()
        print(f"  - [通知] Webhook 通知已成功发送。")
    except requests.exceptions.RequestException as e:
        print(f"  - [错误] 发送 Webhook 通知失败: {e}")

