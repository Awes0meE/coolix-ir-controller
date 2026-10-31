# 第三方依赖与参考

本仓库不打包 `.arduino/`、`.tools/`、`.venv/` 中的第三方工具、库或固件二进制。安装时应保留上游许可证和版权声明。

| 项目 | 用途 | 上游 |
| --- | --- | --- |
| Arduino-IRremote 4.7.1 | UNO 红外收发库，安装版本使用 MIT License | [代码与许可证](https://github.com/Arduino-IRremote/Arduino-IRremote) |
| Arduino AVR core 1.8.8 / Arduino CLI | UNO 编译、上传和串口工具 | [ArduinoCore-avr](https://github.com/arduino/ArduinoCore-avr)、[arduino-cli](https://github.com/arduino/arduino-cli) |
| IRremoteESP8266 | COOLIX 字段、时序和命名参考；不是运行依赖 | [ir_Coolix.h](https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.h)、[ir_Coolix.cpp](https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.cpp)、[LGPL-2.1](https://github.com/crankyoldgit/IRremoteESP8266/blob/master/LICENSE.txt) |
| FastAPI / Uvicorn / pyserial | HTTP 服务与串口通信 | [FastAPI](https://github.com/fastapi/fastapi)、[Uvicorn](https://github.com/encode/uvicorn)、[pyserial](https://github.com/pyserial/pyserial) |
| cloudflared | 可选远程访问隧道 | [官方仓库](https://github.com/cloudflare/cloudflared) |
| Impeccable | 界面设计指导参考 | [官方仓库](https://github.com/pbakaus/impeccable) |

遥控器捕获数据和人工观察由本项目采集。协议常量名称与设备行为可能不同，例如风速位 5 在上游称为 Auto，而本次用户称为“微风”；对应关系在协议文档中区分。
