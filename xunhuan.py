import json
import os
import sys
import time

if sys.platform == "win32":
    import msvcrt
else:
    import select

from manipulator import ManipulatorHand

_QUIT_INPUT_BUFFER = []


def read_quit_command():
    """非阻塞检测退出指令"""
    if sys.platform == "win32":
        while msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ["\r", "\n"]:
                command = "".join(_QUIT_INPUT_BUFFER).strip().lower()
                _QUIT_INPUT_BUFFER.clear()
                return command if command in ["q", "quit"] else None
            if ch == "\003":
                raise KeyboardInterrupt
            if ch in ["\b", "\x7f"]:
                if _QUIT_INPUT_BUFFER:
                    _QUIT_INPUT_BUFFER.pop()
            else:
                _QUIT_INPUT_BUFFER.append(ch)
        return None

    if sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
        command = sys.stdin.readline().strip().lower()
        return command if command in ["q", "quit"] else None
    return None


def load_config():
    """从 config.json 加载配置，文件不存在则使用默认值"""
    default_config = {
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
            {"name": "动作5：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 1.0},
        ],
        "left_actions": [
            {"name": "动作1：大拇指翻转", "positions": [1000, 0, 0, 0, 0, 0], "delay": 0.5},
            {"name": "动作2：大拇指弯曲", "positions": [1000, 1000, 0, 0, 0, 0], "delay": 0.5},
            {"name": "动作3：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 0.5},
            {"name": "动作4：四指弯曲", "positions": [0, 0, 1000, 1000, 1000, 1000], "delay": 1.0},
            {"name": "动作5：全部归零", "positions": [0, 0, 0, 0, 0, 0], "delay": 1.0},
        ],
    }

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        print(f"[WARN] 配置文件 {config_path} 不存在，使用默认配置")
        return default_config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        merged = {**default_config, **user_config}
        print(f"[OK] 已加载配置文件：{config_path}")
        return merged
    except Exception as e:
        print(f"[WARN] 配置文件读取失败：{e}，使用默认配置")
        return default_config


def parse_action_sequence(actions_list):
    """将 config.json 中的动作列表转换为 (name, positions, delay) 元组列表"""
    result = []
    for item in actions_list:
        name = item.get("name", "未命名动作")
        positions = item.get("positions", [0, 0, 0, 0, 0, 0])
        delay = item.get("delay", 0.5)
        result.append((name, positions, delay))
    return result


def multi_hand_action_loop_test():
    """多手多段动作循环测试"""
    config = load_config()

    # 支持命令行参数覆盖配置文件
    args = sys.argv[1:]
    if len(args) >= 1:
        config["control_mode"] = args[0].upper()
    if len(args) >= 2:
        config["right_hand_port"] = args[1]
        config["left_hand_port"] = args[1]
    if len(args) >= 3:
        config["left_hand_port"] = args[2]
    if len(args) >= 4:
        try:
            config["speed"] = int(args[3])
        except ValueError:
            pass
    if len(args) >= 5:
        try:
            config["force"] = int(args[4])
        except ValueError:
            pass

    control_mode = config["control_mode"]
    if control_mode not in ["RIGHT_ONLY", "LEFT_ONLY", "BOTH_HANDS"]:
        print(f"[ERR] 无效的控制模式：{control_mode}，可选：RIGHT_ONLY / LEFT_ONLY / BOTH_HANDS")
        sys.exit(1)

    speed_val = config["speed"]
    force_val = config["force"]
    right_port = config["right_hand_port"]
    left_port = config["left_hand_port"]
    right_action_sequence = parse_action_sequence(config["right_actions"])
    left_action_sequence = parse_action_sequence(config["left_actions"])

    # 初始化机械手，处理串口共享
    right_hand = None
    left_hand = None
    shared_ser = None

    if control_mode in ["RIGHT_ONLY", "BOTH_HANDS"]:
        right_hand = ManipulatorHand(right_port, hand_id=1)
        right_hand.set_speed(speed_val)
        right_hand.set_force(force_val)

    if control_mode in ["LEFT_ONLY", "BOTH_HANDS"]:
        if control_mode == "BOTH_HANDS" and left_port == right_port and right_hand is not None:
            # 同一串口，复用右手的 Serial 实例
            left_hand = ManipulatorHand(left_port, hand_id=2, ser=right_hand.ser)
        else:
            left_hand = ManipulatorHand(left_port, hand_id=2)
        left_hand.set_speed(speed_val)
        left_hand.set_force(force_val)

    mode_desc = {
        "RIGHT_ONLY": "仅右手",
        "LEFT_ONLY": "仅左手",
        "BOTH_HANDS": "两只手同步",
    }
    print("\n===== 进入多手多段动作循环测试模式 =====")
    print(f"[INFO] 控制模式：{mode_desc[control_mode]}")
    print(f"[INFO] 速度值：{speed_val} | 力矩值：{force_val}")
    if right_hand:
        print(f"[INFO] 右手配置：串口{right_port}(ID=1) | 动作序列{len(right_action_sequence)}段")
    if left_hand:
        print(f"[INFO] 左手配置：串口{left_port}(ID=2) | 动作序列{len(left_action_sequence)}段")
    print("[INFO] 操作说明：输入q并回车退出循环 | 按Ctrl+C也可退出")
    print("[INFO] 开始循环执行动作序列...\n")

    try:
        loop_count = 0
        while True:
            loop_count += 1
            print(f"========== 第{loop_count}轮动作序列开始 ==========")

            max_action_count = max(
                len(right_action_sequence) if right_hand else 0,
                len(left_action_sequence) if left_hand else 0,
            )

            for action_idx in range(max_action_count):
                if read_quit_command() in ["q", "quit"]:
                    print("\n[WARN] 收到退出指令，停止循环")
                    raise KeyboardInterrupt

                current_delay = 0

                if right_hand and action_idx < len(right_action_sequence):
                    action_name, pos_list, delay = right_action_sequence[action_idx]
                    right_hand.execute_action(action_name, pos_list)
                    current_delay = max(current_delay, delay)

                if left_hand and action_idx < len(left_action_sequence):
                    action_name, pos_list, delay = left_action_sequence[action_idx]
                    left_hand.execute_action(action_name, pos_list)
                    current_delay = max(current_delay, delay)

                if current_delay > 0:
                    print(f"[INFO] 本轮动作延时{current_delay * 1000:.0f}ms...")
                    time.sleep(current_delay)

            print(f"========== 第{loop_count}轮动作序列完成 ==========\n")

    except KeyboardInterrupt:
        print("\n\n[WARN] 捕获到退出指令，停止循环")
    finally:
        # 先归零两只手（此时串口仍打开），再释放：
        # 复用串口的左手先释放，最后释放拥有串口的右手，避免提前关闭共享串口
        if right_hand:
            right_hand.reset_all_fingers()
        if left_hand:
            left_hand.reset_all_fingers()
        if left_hand:
            del left_hand
        if right_hand:
            del right_hand

    print("===== 多手多段动作循环测试结束，程序正常退出 =====")


if __name__ == "__main__":
    multi_hand_action_loop_test()
