# 示例课程包

`clear-english-speaking-demo.zip` 是一个**完全合成**的课程包，用来验证播放器的导入、播放、变速和 A/B/C 记录链路。

- 音频是本地生成的提示音，不是任何人的录音。
- 文稿是本地生成的 PDF，只包含这几句合成英文。
- 不含任何 BBC 内容。

## 用法

打开 Clear English Speaking（桌面版或网页版），点右上角「导入 ZIP 课程包」，选择这个文件。

## 重新生成

```powershell
python -c "from pathlib import Path; from agent.bbc_course_agent.course import build_demo_package; build_demo_package(Path('examples/clear-english-speaking-demo.zip'))"
```

> 真实的 BBC 课程包只会因你本人主动备课而生成在自己电脑上，永远不要提交到本仓库。
