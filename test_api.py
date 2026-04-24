import anthropic
import os
MODEL="claude-sonnet-4-6"
#创建客户端（API Key 通常通过环境变量 ANTHROPIC_API_KEY 设置）
client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL"),
)

print(f"base_url: {os.getenv('ANTHROPIC_BASE_URL')}")
print(f"model: {MODEL}")
print("Sending test request...")
#发送请求
resp = client.messages.create(
    model=MODEL,
    max_tokens=20,
    messages=[{"role": "user", "content": "Say hello"}],
)
#对于参数role,user为用户,assistant为模型说的话,system为给模型的身份认定
print("Response:", resp.content)
#resp.content是一个列表,每个元素有type和text字段