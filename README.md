# 机械手控制程序

## 项目结构

| 文件               | 说明                                             |
| ------------------ | ------------------------------------------------ |
| `manipulator.py`   | 公共模块 — 机械手控制类（Modbus-RTU 通信、重试机制） |
| `test.py`          | 右手单手控制（交互式点动 + 循环测试）              |
| `xunhuan.py`       | 多手循环控制（支持仅右手/仅左手/双手同步）          |
| `config.json`      | xunhuan.py 的配置文件（串口、速度、动作序列等）     |
| `fix_serial_env.*` | Windows 环境修复脚本（自动安装 pyserial）           |

## 环境要求

- **操作系统**：Windows / macOS / Linux
- **Python 版本**：Python 3.8 及以上
- **硬件**：机械手通过串口（USB 转 RS485）连接电脑

## 安装依赖

本项目唯一依赖的第三方包是 `pyserial`（注意：包名是 **pyserial**，不是 serial）。

```bash
pip install pyserial
```

如果你的电脑上有多个 Python 版本，建议使用：

```bash
python -m pip install pyserial
```

### Windows 一键修复环境

如果安装遇到问题（比如装了错误的 `serial` 包），可以双击运行项目自带的修复脚本：

```
fix_serial_env.bat
```

它会自动查找 Python、卸载错误的 `serial` 包、安装正确的 `pyserial`。

## 串口确认

将机械手通过 USB 转 RS485 连接电脑后，先确认串口号：

- **Windows**：打开设备管理器 → 端口（COM 和 LPT），找到对应的 COM 口（如 COM3、COM19）
- **macOS/Linux**：终端执行 `ls /dev/tty.*` 或 `ls /dev/ttyUSB*`

也可以用 Python 列出所有可用串口：

```bash
python -c "import serial.tools.list_ports; [print(p.device, p.description) for p in serial.tools.list_ports.comports()]"
```

---

## test.py — 单手控制（右手/左手）

### 配置文件 (test_config.json)

test.py 默认读取同目录下的 `test_config.json`，无需每次输入一长串参数。文件不存在时使用内置默认值。

```json
{
    "mode": "test",
    "port": "COM3",
    "speed": 300,
    "force": 300,
    "hand_id": 1,
    "loop_count": 0,
    "loop_actions": [
        {"name": "动作1：大拇指翻转", "positions": [1000, 0, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作2：大拇指弯曲", "positions": [1000, 1000, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作3：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作4：四指弯曲", "positions": [0, 0, 1000, 1000, 1000, 1000], "delay": 1.0},
        {"name": "动作5：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 1.0}
    ]
}
```

| 字段          | 说明                                       | 取值                         |
| ------------- | ------------------------------------------ | ---------------------------- |
| `mode`        | 启动模式                                    | `test`（点动）/ `loop`（循环） |
| `port`        | 串口号                                      | 如 COM3、COM19               |
| `speed`       | 所有手指速度                                | 0 - 1000                     |
| `force`       | 所有手指力矩                                | 0 - 1000                     |
| `hand_id`     | Modbus 从机地址：1=右手，2=左手             | 1 / 2                        |
| `loop_count`  | 循环模式的循环轮数，`0` 表示无限循环         | ≥ 0                          |
| `loop_actions`| 循环模式的动作序列（name/positions/delay） | 数组                         |

### 命令格式（参数均可选，缺省取配置文件）

```
python test.py [test|loop] [串口] [速度] [力矩] [循环次数] [--id 手ID]
```

凡是在命令行给出的参数，都会**覆盖**配置文件中的对应项；未给出的沿用配置文件。`--id`（或 `-i`）可放在任意位置。

```bash
python test.py                          # 全部用配置文件
python test.py loop                     # 仅切到循环模式，其余取配置
python test.py test COM5 500 600        # 覆盖串口/速度/力矩
python test.py loop COM5 500 600 5 --id 2  # 左手循环5轮
python test.py -h                       # 查看用法
```

### 模式一：交互式点动模式 (test)

手动输入 6 个手指的位置值，每次回车立即执行。

```bash
python test.py test COM3 300 300            # 右手(id=1)
python test.py test COM3 300 300 --id 2     # 左手(id=2)
```

进入后输入 6 个 0-1000 的整数（空格分隔），顺序为：

| 序号 | 手指         |
| ---- | ------------ |
| 1    | 大拇指翻转   |
| 2    | 大拇指弯曲   |
| 3    | 食指弯曲     |
| 4    | 中指弯曲     |
| 5    | 无名指弯曲   |
| 6    | 小拇指弯曲   |

**示例操作：**

```
> 500 500 0 0 0 0        # 大拇指翻转500 + 弯曲500，其余不动
> 0 0 1000 1000 1000 1000 # 四指完全弯曲，大拇指不动
> 1000 1000 1000 1000 1000 1000  # 所有手指完全弯曲（握拳）
> 0 0 0 0 0 0             # 所有手指归零（张开）
> q                       # 退出程序，自动归零
```

### 模式二：循环测试模式 (loop)

按预设的动作序列自动循环执行。

```bash
python test.py loop COM3 300 300          # 无限循环（右手）
python test.py loop COM3 300 300 5        # 循环 5 轮后停止
python test.py loop COM3 300 300 5 --id 2 # 控制左手
```

预设动作序列（来自 `test_config.json` 的 `loop_actions`，可自行增删/修改）：

| 步骤 | 动作说明       | 位置值                          | 延时    |
| ---- | -------------- | ------------------------------- | ------- |
| 1    | 大拇指翻转     | [1000, 0, 0, 0, 0, 0]          | 0.5 秒  |
| 2    | 大拇指弯曲     | [1000, 1000, 0, 0, 0, 0]       | 0.5 秒  |
| 3    | 全部归零       | [0, 0, 0, 0, 0, 0]             | 0.5 秒  |
| 4    | 四指弯曲       | [0, 0, 1000, 1000, 1000, 1000] | 1.0 秒  |
| 5    | 全部归零       | [0, 0, 0, 0, 0, 0]             | 1.0 秒  |

循环轮数由配置的 `loop_count` 决定（`0`=无限），也可用命令行第 4 个位置参数覆盖。退出方式：输入 `q` 回车 或 `Ctrl + C`，退出时自动归零。

---

## xunhuan.py — 多手循环控制

### 配置文件 (config.json)

xunhuan.py 通过 `config.json` 配置所有参数（文件不存在时使用默认值）：

```json
{
    "control_mode": "LEFT_ONLY",
    "speed": 1000,
    "force": 1000,
    "right_hand_port": "COM19",
    "left_hand_port": "COM19",
    "right_actions": [
        {"name": "动作1：大拇指翻转", "positions": [1000, 0, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作2：大拇指弯曲", "positions": [1000, 1000, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作3：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作4：四指弯曲", "positions": [0, 0, 1000, 1000, 1000, 1000], "delay": 1.0},
        {"name": "动作5：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 1.0}
    ],
    "left_actions": [
        {"name": "动作1：大拇指翻转", "positions": [1000, 0, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作2：大拇指弯曲", "positions": [1000, 1000, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作3：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 0.5},
        {"name": "动作4：四指弯曲", "positions": [0, 0, 1000, 1000, 1000, 1000], "delay": 1.0},
        {"name": "动作5：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 1.0}
    ]
}
```

| 字段              | 说明                                              |
| ----------------- | ------------------------------------------------- |
| `control_mode`    | `RIGHT_ONLY`（仅右手）/ `LEFT_ONLY`（仅左手）/ `BOTH_HANDS`（双手同步） |
| `speed`           | 速度值（0-1000）                                   |
| `force`           | 力矩值（0-1000）                                   |
| `right_hand_port` | 右手串口号                                         |
| `left_hand_port`  | 左手串口号                                         |
| `right_actions`   | 右手动作序列（每段包含 name、positions、delay）      |
| `left_actions`    | 左手动作序列（格式同上）                             |

### 使用方式

**直接运行**（读取 config.json）：

```bash
python xunhuan.py
```

**命令行参数覆盖配置**（可选）：

```bash
python xunhuan.py <控制模式> [右手串口] [左手串口] [速度] [力矩]
```

示例：

```bash
python xunhuan.py RIGHT_ONLY COM3              # 仅右手，COM3
python xunhuan.py BOTH_HANDS COM3 COM5 500 500  # 双手，不同串口
python xunhuan.py LEFT_ONLY COM19               # 仅左手，COM19
```

退出方式：输入 `q` 回车 或 `Ctrl + C`，退出时自动归零。

### 串口共享说明

当 `BOTH_HANDS` 模式下左右手使用同一个串口时，程序会自动共享同一个串口连接，不会重复打开。

---

## 协议说明

- **通信协议**：Modbus-RTU
- **波特率**：115200
- **从机地址**：1 = 右手，2 = 左手
- **功能码**：
  - `06`：写单个寄存器（设置速度、力矩）
  - `10`（0x10）：写多个寄存器（一条报文同时设置 6 个手指位置）
  - `03`：读寄存器（验证写入结果）
- **数值范围**：所有位置、速度、力矩值均为 0 - 1000
- **重试机制**：通信失败自动重试 3 次，间隔递增（0.1s → 0.2s → 0.3s）

### 寄存器地址映射

| 寄存器地址 | 功能               |
| ---------- | ------------------ |
| 0 - 5      | 位置控制（f1-f6）  |
| 6 - 11     | 速度控制           |
| 12 - 17    | 力矩控制           |
| 47 - 57    | 厂家专用（禁止操作）|

## 常见问题

### 1. 提示 `ModuleNotFoundError: No module named 'serial'`

安装了错误的包。执行：

```bash
pip uninstall serial
pip install pyserial
```

### 2. 串口打开失败

- 检查串口线是否连接
- 确认串口号是否正确
- 确认没有其他程序占用该串口（如串口调试助手）

### 3. 写入后验证失败（WARN）

- 检查波特率是否为 115200
- 检查从机地址是否匹配（右手=1，左手=2）
- 检查机械手是否上电

### 4. config.json 配置不生效

- 确认 config.json 与 xunhuan.py 在同一目录下
- 确认 JSON 格式正确（可用在线 JSON 校验工具检查）
- 命令行参数会覆盖配置文件中的对应项
