import serial
import time
import struct
import sys
import serial.tools.list_ports
import select

if sys.platform == "win32":
    import msvcrt

class ManipulatorRightHand:
    """右手机械手控制器（批量输入所有手指位置值）"""
    # ==================== 官方协议寄存器地址映射（不可修改）====================
    # 位置控制寄存器 (0-5) - 固定顺序：大拇指翻转→大拇指弯曲→食指→中指→无名指→小拇指
    REG_ORDER = [
        0,    # 1.大拇指翻转
        1,    # 2.大拇指弯曲
        2,    # 3.食指弯曲
        3,    # 4.中指弯曲
        4,    # 5.无名指弯曲
        5     # 6.小拇指弯曲
    ]
    FINGER_NAMES = [
        "大拇指翻转",
        "大拇指弯曲",
        "食指弯曲",
        "中指弯曲",
        "无名指弯曲",
        "小拇指弯曲"
    ]

    # 速度控制寄存器 (6-11)
    SPEED_REG_ORDER = [6,7,8,9,10,11]
    # 力矩控制寄存器 (12-17)
    FORCE_REG_ORDER = [12,13,14,15,16,17]

    # 厂家专用寄存器（禁止操作）
    REG_MANU_START = 47
    REG_MANU_END = 57

    def __init__(self, port, slave_id=2, baud=115200):
        """
        初始化右手机械手
        :param port: 串口端口(如COM3)
        :param slave_id: 从机地址(右手固定1)
        :param baud: 波特率(协议固定115200)
        """
        self.slave_id = slave_id
        self.baud = baud
        self.ser = None
        # 初始化串口并校验
        self._init_serial(port)

    def _init_serial(self, port):
        """串口初始化，带可用性校验"""
        try:
            self.ser = serial.Serial(
                port=port,
                baudrate=self.baud,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                bytesize=serial.EIGHTBITS,
                timeout=0.5,
                write_timeout=0.5
            )
            # 清空缓冲区
            self.ser.flushInput()
            self.ser.flushOutput()
            if self.ser.is_open:
                print(f"[OK] 串口{port}初始化成功 | 波特率{self.baud} | 从机地址{self.slave_id}")
        except Exception as e:
            print(f"[ERR] 串口初始化失败：{e}")
            print("[INFO] 可用串口列表：")
            for p in serial.tools.list_ports.comports():
                print(f"   - {p.device} | {p.description}")
            sys.exit(1)

    @staticmethod
    def _crc16_modbus(data):
        """Modbus-RTU标准CRC16校验（多项式0xA001）"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return struct.pack('<H', crc)

    def _write_06(self, reg_addr, value):
        """Modbus 06功能码：写单个寄存器（核心底层方法）"""
        # 1. 校验寄存器合法性
        if self.REG_MANU_START <= reg_addr <= self.REG_MANU_END:
            print(f"[ERR] 禁止操作厂家寄存器：{reg_addr}")
            return False
        # 2. 校验数值范围（协议规定0-1000）
        if not (0 <= value <= 1000):
            print(f"[ERR] 数值{value}超出协议范围[0,1000] | 寄存器{reg_addr}")
            return False
        # 3. 构建06功能码报文（大端打包）
        msg_body = struct.pack('>B B H H', self.slave_id, 0x06, reg_addr, value)
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc
        # 4. 发送报文（强制清空缓冲区）
        try:
            self.ser.flushInput()
            self.ser.flushOutput()
            self.ser.write(full_msg)
            time.sleep(0.05)  # 基础延时
            return True
        except Exception as e:
            print(f"[ERR] 写寄存器{reg_addr}失败：{e}")
            return False

    # ==================== 新增：10功能码写多个寄存器 =====================
    def _write_10(self, reg_start, reg_count, values):
        """Modbus 10功能码（0x10）：写多个寄存器（单报文控制所有手指）"""
        # 1. 合法性校验
        if reg_count < 1 or reg_count > 123:
            print(f"[ERR] 寄存器数量{reg_count}超出范围[1,123]")
            return False
        if len(values) != reg_count:
            print(f"[ERR] 值数量({len(values)})与寄存器数量({reg_count})不匹配")
            return False
        for idx, val in enumerate(values):
            if not (0 <= val <= 1000):
                print(f"[ERR] 第{idx+1}个值({val})超出范围[0,1000]")
                return False
        if self.REG_MANU_START <= reg_start <= self.REG_MANU_END:
            print(f"[ERR] 禁止操作厂家寄存器：起始地址{reg_start}")
            return False

        # 2. 构建10功能码报文（大端打包）
        # 报文结构：从机地址 + 0x10 + 起始寄存器(2) + 寄存器数量(2) + 字节数(1) + 所有值(2*N) + CRC(2)
        header = struct.pack('>B B H H', self.slave_id, 0x10, reg_start, reg_count)
        byte_count = reg_count * 2
        data_vals = b''
        for val in values:
            data_vals += struct.pack('>H', val)
        data_part = struct.pack('>B', byte_count) + data_vals
        msg_body = header + data_part
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc

        # 3. 发送单报文
        try:
            self.ser.flushInput()
            self.ser.flushOutput()
            self.ser.write(full_msg)
            # 打印报文（方便核对）
            hex_msg = ' '.join([f"{b:02X}" for b in full_msg])
            print(f"[OK] 10功能码单报文发送成功 | 报文：{hex_msg}")
            time.sleep(0.2)
            return True
        except Exception as e:
            print(f"[ERR] 10功能码报文发送失败：{e}")
            return False

    def _read_03(self, reg_addr, reg_count=1):
        """Modbus 03功能码：读寄存器（核心底层方法）"""
        if reg_count < 1 or reg_count > 125:
            print(f"[ERR] 读取数量{reg_count}超出范围[1,125]")
            return None
        # 构建03功能码报文
        msg_body = struct.pack('>B B H H', self.slave_id, 0x03, reg_addr, reg_count)
        crc = self._crc16_modbus(msg_body)
        full_msg = msg_body + crc
        # 发送并读取响应
        try:
            self.ser.flushInput()
            self.ser.write(full_msg)
            time.sleep(0.1)
            resp = self.ser.read(self.ser.in_waiting or 10)
            # 解析响应
            if len(resp) < 5 or resp[1] != 0x03:
                print(f"[ERR] 读寄存器{reg_addr}响应异常：{resp.hex() if resp else '无响应'}")
                return None
            # 解析数据（大端解包）
            byte_count = resp[2]
            values = []
            for i in range(0, byte_count, 2):
                val = struct.unpack('>H', resp[3+i:3+i+2])[0]
                values.append(val)
            return values
        except Exception as e:
            print(f"[ERR] 读寄存器{reg_addr}失败：{e}")
            return None

    def set_speed(self, spd_val):
        """预设所有手指速度（协议0-1000），仅执行一次"""
        print(f"\n===== 开始预设所有手指速度 [值：{spd_val}] =====")
        for idx, (reg, name) in enumerate(zip(self.SPEED_REG_ORDER, self.FINGER_NAMES)):
            name = f"{name}速度"
            if self._write_06(reg, spd_val):
                val = self._read_03(reg)
                if val and val[0] == spd_val:
                    print(f"[OK] {name} | 地址{reg} | 写入{spd_val} | 验证成功")
                else:
                    print(f"[WARN] {name} | 地址{reg} | 写入{spd_val} | 验证失败(读取：{val})")
            else:
                print(f"[ERR] {name} | 地址{reg} | 写入失败")

    def set_force(self, for_val):
        """预设所有手指力矩（协议0-1000），仅执行一次"""
        print(f"\n===== 开始预设所有手指力矩 [值：{for_val}] =====")
        for idx, (reg, name) in enumerate(zip(self.FORCE_REG_ORDER, self.FINGER_NAMES)):
            name = f"{name}力矩"
            if self._write_06(reg, for_val):
                val = self._read_03(reg)
                if val and val[0] == for_val:
                    print(f"[OK] {name} | 地址{reg} | 写入{for_val} | 验证成功")
                else:
                    print(f"[WARN] {name} | 地址{reg} | 写入{for_val} | 验证失败(读取：{val})")
            else:
                print(f"[ERR] {name} | 地址{reg} | 写入失败")

    def set_all_fingers_position(self, pos_list):
        """
        批量设置所有手指位置（修改为10功能码单报文）
        :param pos_list: 6个整数的列表，顺序：大拇指翻转→大拇指弯曲→食指→中指→无名指→小拇指
        """
        print(f"\n===== 开始批量设置所有手指位置 | 输入值：{pos_list} =====")
        # 调用10功能码单报文（起始寄存器0，数量6，对应REG_ORDER的0-5）
        if self._write_10(reg_start=0, reg_count=6, values=pos_list):
            # 验证每个寄存器写入结果（保留原有验证逻辑）
            for reg, name, pos_val in zip(self.REG_ORDER, self.FINGER_NAMES, pos_list):
                val = self._read_03(reg)
                if val and val[0] == pos_val:
                    print(f"[OK] {name} | 地址{reg} | 设为{pos_val} | 验证成功")
                else:
                    print(f"[WARN] {name} | 地址{reg} | 设为{pos_val} | 验证失败(读取：{val})")
        else:
            print(f"[ERR] 所有手指位置设置失败")
        print(f"===== 所有手指位置设置完成 =====\n")
        # 整体动作延时，确保所有手指同步完成
        time.sleep(0.2)

    def reset_all_fingers(self):
        """退出时强制所有手指归零（改为10功能码单报文）"""
        print("\n===== 开始所有手指归零 =====")
        zero_list = [0] * 6
        # 10功能码单报文归零
        if self._write_10(reg_start=0, reg_count=6, values=zero_list):
            # 验证归零结果
            for reg, name in zip(self.REG_ORDER, self.FINGER_NAMES):
                val = self._read_03(reg)
                if val and val[0] == 0:
                    print(f"[OK] {name} | 地址{reg} | 归零成功")
                else:
                    print(f"[WARN] {name} | 地址{reg} | 归零失败(当前值：{val})")
        else:
            print("[ERR] 所有手指归零失败")
        print("===== 所有手指归零完成 =====\n")

    def __del__(self):
        """析构函数，确保串口关闭"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("[OK] 串口已安全关闭")

# ==================== 辅助函数：参数校验 =====================
def validate_batch_input(input_str):
    """
    校验批量输入的位置值：
    - 输入q/quit → 返回"quit"
    - 输入6个0-1000的整数 → 返回列表
    - 其他情况 → 返回None
    """
    input_str = input_str.strip().lower()
    # 退出指令
    if input_str in ["q", "quit"]:
        return "quit"
    # 拆分输入为列表
    parts = input_str.split()
    # 校验数量是否为6个
    if len(parts) != 6:
        print(f"[ERR] 输入错误！需要输入6个位置值（空格分隔），当前输入了{len(parts)}个")
        return None
    # 校验每个值是否为0-1000的整数
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


def validate_speed_force(speed_arg, force_arg):
    """校验速度和力矩参数，不合法时回退默认值。"""
    try:
        speed_val = int(speed_arg)
        force_val = int(force_arg)
        speed_val = speed_val if 0 <= speed_val <= 1000 else 300
        force_val = force_val if 0 <= force_val <= 1000 else 300
    except ValueError:
        speed_val = 300
        force_val = 300
        print(f"[WARN] 速度/力矩参数不合法，使用默认值：速度={speed_val}，力矩={force_val}")
    return speed_val, force_val


def print_usage():
    """打印命令行使用说明。"""
    print("===== 右手机械手控制程序 =====")
    print("[INFO] 支持命令：test / loop")
    print("[INFO] 命令格式：")
    print("   python test.py test <串口端口> <速度值(0-1000)> <力矩值(0-1000)>")
    print("   python test.py loop <串口端口> <速度值(0-1000)> <力矩值(0-1000)> [循环次数]")
    print("[INFO] 示例：")
    print("   python test.py test COM3 300 300")
    print("   python test.py loop COM3 300 300")
    print("   python test.py loop COM3 300 300 5")
    print("[INFO] 兼容旧格式：")
    print("   python test.py COM3 300 300")


def read_quit_command():
    """非阻塞检测退出指令。"""
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
    """进入交互式测试模式。"""
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


def run_loop_mode(robot, loop_limit=None):
    """进入循环测试模式。"""
    action_sequence = [
        ("动作1：大拇指翻转500", [1000, 0, 0, 0, 0, 0], 0.5),
        ("动作2：大拇指弯曲500", [1000, 1000, 0, 0, 0, 0], 0.5),
        ("动作3：食指弯曲500", [0, 0, 0, 0, 0, 0], 0.5),
        ("动作4：全部归零", [0, 0, 1000, 1000, 1000, 1000], 1.0),
        ("动作4：全部归零", [0, 0, 0, 0, 0, 0], 1.0),
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

# ==================== 主程序：批量位置控制逻辑 =====================
if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        print_usage()
        sys.exit(1)

    if args[0] in ["test", "loop"]:
        command = args[0]
        if len(args) < 4:
            print_usage()
            sys.exit(1)
        PORT = args[1]
        SPEED_VAL, FORCE_VAL = validate_speed_force(args[2], args[3])
        loop_limit = None
        if command == "loop" and len(args) >= 5:
            try:
                loop_limit = int(args[4])
                if loop_limit <= 0:
                    print("[WARN] 循环次数必须大于0，将使用无限循环模式")
                    loop_limit = None
            except ValueError:
                print("[WARN] 循环次数参数不合法，将使用无限循环模式")
                loop_limit = None
    else:
        if len(args) != 3:
            print_usage()
            sys.exit(1)
        command = "test"
        PORT = args[0]
        SPEED_VAL, FORCE_VAL = validate_speed_force(args[1], args[2])
        loop_limit = None

    # 1. 初始化右手机械手
    robot = ManipulatorRightHand(PORT)

    # 2. 一次性预设所有手指的速度和力矩
    robot.set_speed(SPEED_VAL)
    robot.set_force(FORCE_VAL)

    try:
        if command == "loop":
            run_loop_mode(robot, loop_limit)
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
