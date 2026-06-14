import sys
import time
import json
import os

if sys.platform == "win32":
    import msvcrt
else:
    import select

from manipulator import ManipulatorHand

CONFIG_FILENAME = "test_config.json"

# 默认配置（test_config.json 缺失或字段缺失时回退）
DEFAULT_CONFIG = {
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
        {"name": "动作5：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 1.0},
    ],
}


def load_config():
    """从 test_config.json 加载配置，文件/字段缺失时回退默认值"""
    config = dict(DEFAULT_CONFIG)
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILENAME)
    if not os.path.exists(config_path):
        print(f"[WARN] 配置文件 {config_path} 不存在，使用默认配置")
        return config
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        config.update(user_config)
        print(f"[OK] 已加载配置文件：{config_path}")
    except Exception as e:
        print(f"[WARN] 配置文件读取失败：{e}，使用默认配置")
    return config


def parse_action_sequence(actions_list):
    """将动作字典列表转换为 (name, positions, delay) 元组列表"""
    result = []
    for item in actions_list:
        name = item.get("name", "未命名动作")
        positions = item.get("positions", [0, 0, 0, 0, 0, 0])
        delay = item.get("delay", 0.5)
        result.append((name, positions, delay))
    return result


def to_range(val, default, lo=0, hi=1000):
    """将 val 转为 [lo,hi] 内的整数，非法时回退 default"""
    try:
        v = int(val)
    except (ValueError, TypeError):
        print(f"[WARN] 数值 {val} 不合法，使用默认 {default}")
        return default
    if not (lo <= v <= hi):
        print(f"[WARN] 数值 {v} 超出范围[{lo},{hi}]，使用默认 {default}")
        return default
    return v


def validate_batch_input(input_str):
    """校验批量输入的位置值"""
    input_str = input_str.strip().lower()
    if input_str in ["q", "quit"]:
        return "quit"
    parts = input_str.split()
    if len(parts) != 6:
        print(f"[ERR] 输入错误！需要输入6个位置值（空格分隔），当前输入了{len(parts)}个")
        return None
    try:
        pos_list = [int(p) for p in parts]
        for idx, val in enumerate(pos_list):
            if not (0 <= val <= 1000):
                print(f"[ERR] 第{idx+1}个值({val})超出范围！必须是0-1000之间的整数")
                return None
        return pos_list
    except ValueError:
        print("[ERR] 输入错误！所有值必须是整数（0-1000）")
        return None


def print_usage():
    print("===== 机械手控制程序 =====")
    print("[INFO] 默认读取 test_config.json，命令行参数可覆盖其中各项")
    print("[INFO] 支持命令：test（点动） / loop（循环）")
    print("[INFO] 从机地址：--id 1=右手，--id 2=左手")
    print("[INFO] 命令格式（参数均可选，缺省取配置文件）：")
    print("   python test.py [test|loop] [串口] [速度] [力矩] [循环次数] [--id 手ID]")
    print("[INFO] 示例：")
    print("   python test.py                          # 全部用配置文件")
    print("   python test.py loop                     # 切到循环模式，其余取配置")
    print("   python test.py test COM3 300 300        # 覆盖串口/速度/力矩")
    print("   python test.py loop COM3 300 300 5 --id 2")
    print("   python test.py -h                       # 显示本说明")


def extract_hand_id(args, default=1):
    """从参数列表中提取并移除 --id/-i <值>，返回 (hand_id, 剩余参数)。

    按协议约定：1=右手，2=左手。
    """
    hand_id = default
    result = []
    i = 0
    while i < len(args):
        if args[i] in ("--id", "-i"):
            if i + 1 < len(args):
                try:
                    hand_id = int(args[i + 1])
                except ValueError:
                    print(f"[WARN] --id 参数不合法：{args[i+1]}，使用默认 {default}")
                i += 2
                continue
            print(f"[WARN] --id 缺少值，使用默认 {default}")
            i += 1
            continue
        result.append(args[i])
        i += 1
    if hand_id is not None and hand_id not in (1, 2):
        print(f"[WARN] hand_id={hand_id} 不在协议约定 [1=右手, 2=左手] 内，仍按该地址通信")
    return hand_id, result


def read_quit_command():
    """非阻塞检测退出指令"""
    if sys.platform == "win32":
        chars = []
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ["\r", "\n"]:
                command = "".join(chars).strip().lower()
                return command if command in ["q", "quit"] else None
            if ch == "\003":
                raise KeyboardInterrupt
            chars.append(ch)
        return None

    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        command = sys.stdin.readline().strip().lower()
        if command in ["q", "quit"]:
            return command
    return None


def run_interactive_test_mode(robot):
    """交互式点动测试模式"""
    print("\n===== 进入批量位置控制测试模式 =====")
    print("[INFO] 输入顺序（6个值，空格分隔）：")
    print("   1. 大拇指翻转  2. 大拇指弯曲  3. 食指弯曲")
    print("   4. 中指弯曲    5. 无名指弯曲  6. 小拇指弯曲")
    print("[INFO] 操作说明：")
    print("   - 输入6个0-1000的整数（空格分隔），按回车发送1条报文同步设置所有手指位置")
    print("   - 输入q/quit，所有手指归零并退出程序")

    while True:
        user_input = input("\n> 请输入6个手指的位置值（空格分隔），输入q/quit退出：")
        pos_list = validate_batch_input(user_input)
        if pos_list == "quit":
            robot.reset_all_fingers()
            print("===== 退出批量位置控制测试模式 =====")
            break
        if pos_list is not None:
            robot.set_all_fingers_position(pos_list)


def run_loop_mode(robot, loop_limit=None, action_sequence=None):
    """循环测试模式"""
    if action_sequence is None:
        action_sequence = [
            ("动作1：大拇指翻转", [1000, 0, 0, 0, 0, 0], 0.5),
            ("动作2：大拇指弯曲", [1000, 1000, 0, 0, 0, 0], 0.5),
            ("动作3：全部归零", [0, 0, 0, 0, 0, 0], 0.5),
            ("动作4：四指弯曲", [0, 0, 1000, 1000, 1000, 1000], 1.0),
            ("动作5：全部归零", [0, 0, 0, 0, 0, 0], 1.0),
        ]

    print("\n===== 进入循环测试模式 =====")
    print(f"[INFO] 动作序列共{len(action_sequence)}段")
    if loop_limit is None:
        print("[INFO] 循环次数：无限循环")
    else:
        print(f"[INFO] 循环次数：{loop_limit}轮")
    print("[INFO] 操作说明：输入q并回车退出循环 | 按Ctrl+C也可退出")

    loop_count = 0
    while True:
        if loop_limit is not None and loop_count >= loop_limit:
            print("\n[INFO] 已达到设定循环次数，准备退出")
            break

        loop_count += 1
        print(f"\n========== 第{loop_count}轮动作开始 ==========")

        for action_name, pos_list, delay in action_sequence:
            if read_quit_command() in ["q", "quit"]:
                print("\n[WARN] 收到退出指令，停止循环")
                return

            print(f"[INFO] 执行{action_name} | 值：{pos_list}")
            robot.set_all_fingers_position(pos_list)
            if delay > 0:
                print(f"[INFO] 延时{int(delay * 1000)}ms")
                time.sleep(delay)

        print(f"========== 第{loop_count}轮动作完成 ==========")


if __name__ == "__main__":
    args = sys.argv[1:]

    if any(a in ("-h", "--help") for a in args):
        print_usage()
        sys.exit(0)

    # 1. 提取从机地址（--id）；命令行未给时为 None，稍后回退配置
    cli_hand_id, args = extract_hand_id(args, default=None)

    # 2. 读取配置文件作为默认值
    config = load_config()
    command = config["mode"]
    PORT = config["port"]
    SPEED_VAL = to_range(config["speed"], 300)
    FORCE_VAL = to_range(config["force"], 300)
    HAND_ID = cli_hand_id if cli_hand_id is not None else config["hand_id"]
    loop_count = config.get("loop_count", 0)
    loop_limit = loop_count if isinstance(loop_count, int) and loop_count > 0 else None
    action_sequence = parse_action_sequence(config["loop_actions"])

    # 3. 命令行位置参数覆盖配置：[test|loop] [串口] [速度] [力矩] [循环次数]
    if args and args[0] in ("test", "loop"):
        command = args[0]
        args = args[1:]
    if len(args) >= 1:
        PORT = args[0]
    if len(args) >= 2:
        SPEED_VAL = to_range(args[1], SPEED_VAL)
    if len(args) >= 3:
        FORCE_VAL = to_range(args[2], FORCE_VAL)
    if len(args) >= 4:
        try:
            n = int(args[3])
            loop_limit = n if n > 0 else None
        except ValueError:
            print("[WARN] 循环次数参数不合法，沿用配置/无限循环")

    # 4. 校验最终值
    if command not in ("test", "loop"):
        print(f"[WARN] mode={command} 非法，回退为 test")
        command = "test"
    if HAND_ID not in (1, 2):
        print(f"[WARN] hand_id={HAND_ID} 不在协议约定 [1=右手, 2=左手] 内，仍按该地址通信")

    hand_label = "右手" if HAND_ID == 1 else "左手"
    print(f"[INFO] 启动配置 | 模式:{command} | 串口:{PORT} | 速度:{SPEED_VAL} | 力矩:{FORCE_VAL} | 手ID:{HAND_ID}({hand_label})")

    # 按协议用 hand_id 指定从机地址（1=右手，2=左手），名称自动推断
    robot = ManipulatorHand(PORT, hand_id=HAND_ID)
    robot.set_speed(SPEED_VAL)
    robot.set_force(FORCE_VAL)

    try:
        if command == "loop":
            run_loop_mode(robot, loop_limit, action_sequence)
        else:
            run_interactive_test_mode(robot)
    except KeyboardInterrupt:
        print("\n\n[WARN] 捕获到中断指令，开始所有手指归零 =====")
        robot.reset_all_fingers()
    finally:
        if robot.ser and robot.ser.is_open:
            robot.reset_all_fingers()
        del robot

    print("===== 程序正常退出 =====")
