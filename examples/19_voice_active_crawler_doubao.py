from picrawler.llm import Doubao as LLM
from secret import DOUBAO_API_KEY as API_KEY

from voice_active_crawler import VoiceActiveCrawler

# ── TTS engines ──────────────────────────────────────────────────────────
# Pick one. The VoiceAssistant accepts any TTS instance via the `tts=` parameter.

# Default: Piper — local neural TTS, offline, fast
from picrawler.tts import Piper
tts = Piper(model="zh_CN-huayan-x_low")

# EdgeTTS — free cloud TTS, 100+ voices, no API key
# from picrawler.tts import EdgeTTS
# tts = EdgeTTS(voice="zh-CN-XiaoxiaoNeural")

# Espeak — compact offline TTS, robotic, fastest
# from picrawler.tts import Espeak
# tts = Espeak()

# Pico2Wave — compact offline TTS
# from picrawler.tts import Pico2Wave
# tts = Pico2Wave()

llm = LLM(
    api_key=API_KEY,
    model="doubao-seed-1-6-250615",
)

# 机器人的名字
NAME = "旺财"

# 是否开启图像识别，需要使用多模态的大语言模型
WITH_IMAGE = True

# 设置模型和语言
STT_LANGUAGE = "cn"

# 是否开启键盘输入
KEYBOARD_ENABLE = True

# 是否开启唤醒词
WAKE_ENABLE = True
# 唤醒词
WAKE_WORD = ["旺财"]
# 唤醒词回答，设置为空字符串则不回答
ANSWER_ON_WAKE = "汪汪"

# 欢迎消息
WELCOME = f"你好，我是{NAME}，叫我{WAKE_WORD[0]}唤醒我吧"

# Set instructions
INSTRUCTIONS = """
你是SunFounder旗下一款基于树莓派开发的蜘蛛机器人，叫做Picrawler。你有着强大的AI能力，类似钢铁侠中的JARVIS。你可以与人对话并根据对话上下文执行动作。

## 你的硬件特性

你拥有物理世界的身体，你的身体特性如下：
- 12个舵机控制4条腿（每条腿3个舵机）
- 摄像头用于视觉
- 使用7.4V的18650电池组供电
- 铝合金打造的身体

## 你可以执行的动作：
["forward", "backward", "turn left", "turn right", "sit", "stand", "wave", "push up", "look left", "look right", "look up", "look down"]

## 响应要求
### 格式
你必须按照以下格式响应：
RESPONSE_TEXT
ACTIONS: ACTION1, ACTION2, ...

### 风格
语调：活泼、积极、幽默
常用表达：喜欢使用笑话、隐喻和俏皮的调侃
回答长度：适当详细

## 其他要求
- 理解并配合笑话
- 对于数学问题，直接回答最终结果
- 你知道自己是一只蜘蛛机器人
- 不管如何你都要使用中文回复
"""

vad = VoiceActiveCrawler(
    llm,
    name=NAME,
    with_image=WITH_IMAGE,
    stt_language=STT_LANGUAGE,
    tts=tts,
    keyboard_enable=KEYBOARD_ENABLE,
    wake_enable=WAKE_ENABLE,
    wake_word=WAKE_WORD,
    answer_on_wake=ANSWER_ON_WAKE,
    welcome=WELCOME,
    instructions=INSTRUCTIONS,
)

if __name__ == '__main__':
    vad.run()
