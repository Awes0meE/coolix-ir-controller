# COOLIX IR Controller

面向用户的说明使用简体中文；代码和技术标识保持英文。

本项目以 UNO R3、YORK RG94A/BGEF 和 COOLIX 协议实现个人手机空调遥控。
技术栈：AVR C++ / IRremote 4.7.1、Python / FastAPI / pyserial、原生 HTML/CSS/JS。

## 入口与命令

- README 是安装入口；docs/COOLIX状态编码.md 是协议解释；docs/验证范围.md 是验证边界。
- 配置示例为 .env.example，实际配置在被忽略的 .runtime/controller/service.env。
- `sh controller/run.sh` 启动 127.0.0.1:8768；需要实际 IR_SERIAL_PORT。
- `.venv/bin/python -m pytest -q tests`；`node --check controller/static/app.js`。
- `sh scripts/arduino.sh compile --fqbn arduino:avr:uno sketches/ACStateControl` 只编译。
- `.venv/bin/python scripts/check_public_tree.py` 检查公开文件与本地文档链接。

## 必须保持的边界

- 启动、刷新、后台 STATUS 查询和软件测试不发红外；用户明确创建的定时任务与预制冷阶段可按计划执行，实物控制必须在用户授权范围内。
- 定时任务持久化在原数据库；启动时不补发到期任务，运行中错过超过 30 秒不补发，结果不明不重试。
- 手动控制或定时开关机接管前取消后续预制冷阶段；取消任务本身不发送红外。
- Web 服务独占串口；上传前停服务，监视器与服务不可同时打开。
- TX_DONE 不是空调实际反馈；不把原遥控器状态或绝对扇叶角度猜成已知。
- 普通命令保留 5 秒间隔、递增序号和持久化请求防重发；模糊结果不自动重试。
- CYCLE24 是历史明确请求的一次性实验命令，不在网页/API 中暴露。
- Sleep 样本含固定温度/风量；AUTO/DRY 锁定风量；FAN 没有温度。
- 捕获异常保留为异常，不为得到完整样本而补造时序。
- CapturedButtons.h 和 york-replay-index.json 由 generate_replay_catalog.py 生成，不手改。
- .runtime、凭据、数据库、工具依赖与编译产物不进 Git；日志只提交审查过的协议证据。
- 代码公开不意味着私有控制站可公开免登录。
- 许可范围以 LICENSING.md 为准；保留 NOTICE 和适用的第三方声明。
- 提交使用 Conventional Commits；功能分支使用 feat/、fix/、docs/ 等语义前缀。

## 当前状态与下一步

已实现五模式、17–30°C、四档风量、11 个原始样本、定时开关机、两阶段预制冷和需要访问码的手机网页。
验证范围与未确认功能集中在 docs/验证范围.md；不要在此复制动态部署状态。
后续重点是完善定时、预制冷与特殊功能的实物验证；不能推断室内机支持制热。
